#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - collecte, analyse et publication."""

import datetime as dt
import json
from zoneinfo import ZoneInfo

from pmu_engine import collecter
from phoenix import (
    DATA, FIGES, analyser, figer,
    lire, ecrire, verifier_fige
)

PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def maintenant():
    return dt.datetime.now(PARIS).isoformat()


def charger(nom, cle, erreurs):
    chemin = DATA / (nom + ".json")
    if not chemin.exists():
        return []
    try:
        objet = lire(chemin)
        if isinstance(objet, list):
            return objet
        if isinstance(objet, dict):
            valeur = objet.get(cle)
            if isinstance(valeur, list):
                return valeur
        raise ValueError("Format incorrect")
    except (OSError, ValueError, TypeError) as exc:
        erreurs.append(f"{chemin}: {exc}")
        return []


def documents(dossier, erreurs, verifier=False):
    resultat = []
    for chemin in sorted((DATA / dossier).glob("*.json")):
        try:
            objet = lire(chemin)
            if not isinstance(objet, dict):
                raise ValueError("Document non objet")
            if verifier:
                verifier_fige(objet)
            resultat.append(objet)
        except (
            OSError, ValueError, TypeError, KeyError
        ) as exc:
            erreurs.append(f"{chemin}: {exc}")
    return resultat


def rapport_fige(document):
    if isinstance(document.get("rapport"), dict):
        return document["rapport"]

    contenu = document.get("contenu")
    if (
        isinstance(contenu, dict)
        and isinstance(contenu.get("analyse"), dict)
    ):
        return contenu["analyse"]

    raise ValueError("Format FIGE inconnu")


def moteurs_site(moteurs):
    if not isinstance(moteurs, list):
        return []

    resultat = []
    for moteur in moteurs:
        if not isinstance(moteur, dict):
            continue
        copie = dict(moteur)
        if (
            "ordre_espere" not in copie
            and isinstance(copie.get("ordre"), list)
        ):
            copie["ordre_espere"] = copie["ordre"][:5]
        resultat.append(copie)
    return resultat


def unique(objets, cle):
    resultat = []
    vus = set()

    for objet in objets:
        if not isinstance(objet, dict):
            continue
        valeur = objet.get(cle)
        if valeur is None or valeur in vus:
            continue
        vus.add(valeur)
        resultat.append(objet)

    return resultat


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    FIGES.mkdir(parents=True, exist_ok=True)

    erreurs = []

    try:
        collecte = collecter()
        if not isinstance(collecte, dict):
            raise ValueError("Collecte invalide")

        erreurs.extend(
            str(e) for e in collecte.get("erreurs", [])
        )
        courses_brutes = collecte.get("courses", [])

        if not isinstance(courses_brutes, list):
            raise ValueError("Courses invalides")

    except (
        OSError, ValueError, TypeError, KeyError
    ) as exc:
        collecte = {}
        courses_brutes = []
        erreurs.append(
            f"Collecte PMU indisponible: {exc}"
        )

    courses = []
    pv = []

    for course in courses_brutes:
        if not isinstance(course, dict):
            erreurs.append("Course invalide ignoree")
            continue

        cid = course.get("id")
        if not cid:
            erreurs.append("Course sans ID")
            continue

        ligne = dict(course)
        ligne["statut"] = "DONNEES_NON_ANALYSEES"

        try:
            analyse = analyser(course)

            ligne["moteurs"] = moteurs_site(
                analyse.get("moteurs", [])
            )
            ligne["analyse_a"] = analyse.get("analyse_a")
            ligne["statut"] = "ANALYSE_INDICATIVE"

            entree = {
                "pv_id": "ANALYSE-" + str(cid),
                "course_id": cid,
                "type": "PV_ANALYSE",
                "statut": "PV_ANALYSE_NON_FIGE",
                "cree_a": analyse.get("analyse_a"),
                "depart": analyse.get("depart"),
                "source": analyse.get("source"),
                "moteurs": ligne["moteurs"]
            }

            document = figer(analyse)

            if document is not None:
                verifier_fige(document)
                entree["statut"] = "FIGE_VERIFIE"
                entree["sha256"] = document["sha256"]
                ligne["statut"] = "FIGE_VERIFIE"

            pv.append(entree)

        except (
            ValueError, KeyError, TypeError, OSError
        ) as exc:
            erreurs.append(f"{cid}: {exc}")

        courses.append(ligne)

    # Conserver les FIGES originaux sans les modifier.
    figes = documents(
        "figes", erreurs, verifier=True
    )

    for document in charger("figes", "figes", erreurs):
        try:
            verifier_fige(document)
            figes.append(document)
        except (
            ValueError, KeyError, TypeError
        ) as exc:
            erreurs.append(
                f"FIGE historique rejete: {exc}"
            )

    figes = unique(figes, "sha256")

    # Conserver les PV historiques.
    pv = unique(
        pv + charger("pv", "pv", erreurs),
        "pv_id"
    )

    # Les audits exigent des arrivees documentees.
    audits = documents("audits", erreurs)
    audits += charger("audits", "audits", erreurs)

    audits_valides = []
    for audit in audits:
        if (
            audit.get("statut") == "AUDIT_EFFECTUE"
            and audit.get("fige_sha256")
            and (
                audit.get("source_arrivee")
                or audit.get("source_resultat")
            )
            and isinstance(
                audit.get("arrivee_officielle"), list
            )
            and len(audit["arrivee_officielle"]) >= 5
        ):
            audits_valides.append(audit)

    audits = unique(audits_valides, "course_id")

    # Reprendre les selections des FIGES verifies.
    index = {
        c["id"]: c for c in courses if c.get("id")
    }

    for document in figes:
        analyse = rapport_fige(document)
        cid = analyse.get("course_id")

        if not cid:
            continue

        if cid not in index:
            ligne = {
                "id": cid,
                "hippodrome": analyse.get("hippodrome"),
                "depart": analyse.get("depart"),
                "source": analyse.get("source"),
                "nombre_partants": analyse.get(
                    "nombre_partants"
                ),
                "moteurs": moteurs_site(
                    analyse.get("moteurs", [])
                ),
                "statut": "FIGE_VERIFIE"
            }
            courses.append(ligne)
            index[cid] = ligne
        else:
            index[cid]["moteurs"] = moteurs_site(
                analyse.get("moteurs", [])
            )
            index[cid]["statut"] = "FIGE_VERIFIE"

    analyses_count = sum(
        bool(c.get("moteurs")) for c in courses
    )

    if not courses:
        statut = "DONNEES_INDISPONIBLES"
    elif analyses_count == 0:
        statut = "COURSES_SANS_ANALYSES"
    elif erreurs:
        statut = "PUBLICATION_PARTIELLE"
    else:
        statut = "PUBLICATION_OK"

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": "PUBLICATION-UNIFIEE-5.0",
        "status": statut,
        "generated_at_paris": maintenant(),
        "moteurs_actifs": list(MOTEURS),
        "source_donnees": collecte.get("source"),
        "courses_collectees": len(courses_brutes),
        "courses_count": len(courses),
        "analyses_count": analyses_count,
        "pv_count": len(pv),
        "figes_count": len(figes),
        "audits_count": len(audits),
        "difficultes": [
            {
                "moteur": "SYSTEME",
                "difficulte": erreur
            }
            for erreur in erreurs
        ],
        "avertissement": (
            "Aucune course ou arrivee inventee. "
            "FIGES originaux conserves."
        )
    }

    # Publication des cinq fichiers pour le site.
    publications = (
        ("courses", "courses", courses),
        ("pv", "pv", pv),
        ("figes", "figes", figes),
        ("audits", "audits", audits)
    )

    for nom, cle, objets in publications:
        ecrire(
            DATA / f"publication_{nom}.json",
            {cle: objets}
        )

    ecrire(
        DATA / "publication_rapport.json",
        rapport
    )

    print(json.dumps(
        rapport,
        ensure_ascii=False,
        indent=2
    ))


if __name__ == "__main__":
    main()
