#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX — PUBLICATION UNIFIEE M1-M5
Version 8.0

- Analyses M1-M5
- Controle avant depart
- Publication PV
- Conservation des FIGES historiques
- Verification SHA256
- Audits sans resultats inventes
- Compatible GitHub Actions / GitHub Pages

IMPORTANT :
Ce module ne valide pas lui-meme de nouveaux FIGES.
Une source independante et une validation pre-depart
sont necessaires avant leur creation.
"""

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import (
    DATA,
    FIGES,
    lire,
    ecrire,
    verifier_fige,
    controle_fige,
    rapport_fige,
)

from analyser_moteurs import analyser as analyser_moteurs

PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")
VERSION = "PUBLICATION-UNIFIEE-8.0"


def maintenant():
    return dt.datetime.now(PARIS)


def date_heure(valeur):
    if not isinstance(valeur, str):
        raise ValueError("Date absente")

    instant = dt.datetime.fromisoformat(
        valeur.replace("Z", "+00:00")
    )

    if instant.tzinfo is None:
        raise ValueError("Fuseau horaire absent")

    return instant.astimezone(PARIS)


def collection(nom, cle, erreurs):
    chemin = DATA / (nom + ".json")

    if not chemin.is_file():
        return []

    try:
        objet = lire(chemin)

        if isinstance(objet, list):
            return objet

        if isinstance(objet, dict):
            lignes = objet.get(cle)
            if isinstance(lignes, list):
                return lignes

        raise ValueError("Collection JSON invalide")

    except (OSError, ValueError, TypeError) as exc:
        erreurs.append(f"{chemin.name}: {exc}")
        return []


def archives(dossier, erreurs, figes=False):
    resultat = []

    for chemin in sorted(
        (DATA / dossier).glob("*.json")
    ):
        try:
            document = lire(chemin)

            if not isinstance(document, dict):
                raise ValueError("Document non objet")

            if figes:
                verifier_fige(document)

            resultat.append(document)

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            erreurs.append(
                f"Archive {chemin.name}: {exc}"
            )

    return resultat


def uniques(documents, cle):
    resultat = []
    vus = set()

    for document in documents:
        if not isinstance(document, dict):
            continue

        valeur = document.get(cle)

        if (
            not isinstance(valeur, (str, int))
            or isinstance(valeur, bool)
        ):
            continue

        identifiant = str(valeur)

        if identifiant in vus:
            continue

        vus.add(identifiant)
        resultat.append(document)

    return resultat


def charger_figes(erreurs):
    candidats = archives(
        "figes", erreurs, figes=True
    )

    for document in collection(
        "figes", "figes", erreurs
    ):
        try:
            verifier_fige(document)
            candidats.append(document)
        except (ValueError, TypeError, KeyError) as exc:
            erreurs.append(
                f"FIGE historique invalide: {exc}"
            )

    resultat = []
    vus = set()

    for document in candidats:
        sha = document.get("sha256")

        if not isinstance(sha, str):
            continue

        try:
            cid = str(
                rapport_fige(document)["course_id"]
            )
        except (ValueError, TypeError, KeyError):
            continue

        cle = (cid, sha.lower())

        if cle in vus:
            continue

        vus.add(cle)
        resultat.append(document)

    return resultat


def charger_audits(erreurs, figes):
    empreintes = {
        f["sha256"].lower()
        for f in figes
        if isinstance(f.get("sha256"), str)
    }

    candidats = (
        archives("audits", erreurs)
        + collection("audits", "audits", erreurs)
    )

    resultat = []

    for audit in candidats:
        sha = audit.get("fige_sha256")
        arrivee = audit.get("arrivee_officielle")
        source = (
            audit.get("source_arrivee")
            or audit.get("source_resultat")
        )

        structure_valide = (
            isinstance(sha, str)
            and sha.lower() in empreintes
            and audit.get("statut") == "AUDIT_EFFECTUE"
            and isinstance(source, str)
            and source.startswith("https://")
            and isinstance(arrivee, list)
            and len(arrivee) >= 5
            and all(
                type(n) is int and n > 0
                for n in arrivee
            )
            and len(set(arrivee)) == len(arrivee)
        )

        if structure_valide:
            copie = dict(audit)
            copie["verification_publication"] = (
                "STRUCTURE_VALIDE_SOURCE_NON_REVERIFIEE"
            )
            resultat.append(copie)
        else:
            erreurs.append(
                "Audit incomplet ou incoherent: "
                + str(audit.get("course_id", "?"))
            )

    return resultat


def normaliser_moteurs(analyse):
    bloc = analyse.get("moteurs", [])

    if isinstance(bloc, dict):
        bloc = [
            dict(valeur, moteur=nom)
            for nom, valeur in bloc.items()
            if isinstance(valeur, dict)
        ]

    if not isinstance(bloc, list):
        return []

    resultat = []
    vus = set()

    for moteur in bloc:
        if not isinstance(moteur, dict):
            continue

        nom = moteur.get("moteur")

        if nom not in MOTEURS or nom in vus:
            continue

        vus.add(nom)

        ordre = (
            moteur.get("ordre_espere")
            or moteur.get("ordre_arrivee_espere")
            or []
        )

        if not isinstance(ordre, list):
            continue

        try:
            numeros = [
                int(n)
                for n in ordre
                if type(n) is int
                or (
                    isinstance(n, str)
                    and re.fullmatch(r"[1-9]\d*", n)
                )
            ]
        except (TypeError, ValueError):
            continue

        if (
            len(numeros) != len(ordre)
            or len(set(numeros)) != len(numeros)
            or any(n <= 0 for n in numeros)
        ):
            continue

        top = numeros[:5]

        resultat.append({
            "moteur": nom,
            "gagnant_espere": (
                top[0] if top else None
            ),
            "meilleur_place": (
                top[1] if len(top) > 1 else None
            ),
            "ordre_espere": top,
            "ordre_arrivee_espere": top,
            "classement_complet": (
                moteur.get("classement_complet", [])
            ),
            "qualification": "ETUDE_NON_VALIDEE",
            "validation": "NON_FIGE",
            "pari_retenu": None,
            "methode": "HEURISTIQUE_MUSIQUE",
        })

    return resultat


def controle_avant_depart(course, instant):
    """Controle local, sans prétendre verifier le PMU."""
    raisons = []

    if not isinstance(course, dict):
        return False, ["Course invalide"]

    if course.get("localisation_france_verifiee") is not True:
        raisons.append("Localisation non confirmee")

    if course.get("depart_verifie") is not True:
        raisons.append("Depart non confirme")

    try:
        depart = date_heure(course.get("depart"))
        if instant >= depart:
            raisons.append("Depart atteint ou passe")
    except (ValueError, TypeError, OverflowError):
        raisons.append("Horaire invalide")

    partants = course.get("partants")

    if not isinstance(partants, list) or not partants:
        raisons.append("Partants absents")
    else:
        numeros = set()
        actifs = 0

        for cheval in partants:
            if not isinstance(cheval, dict):
                raisons.append("Fiche cheval invalide")
                continue

            numero = cheval.get("numero")

            if (
                type(numero) is int
                and numero > 0
            ):
                n = numero
            elif (
                isinstance(numero, str)
                and re.fullmatch(
                    r"[1-9]\d*", numero.strip()
                )
            ):
                n = int(numero.strip())
            else:
                raisons.append("Numero invalide")
                continue

            if n in numeros:
                raisons.append("Numero duplique")

            numeros.add(n)

            if (
                cheval.get("non_partant") is not True
                and str(
                    cheval.get("statut", "")
                ).upper() not in (
                    "NON_PARTANT",
                    "NON-PARTANT",
                    "NP",
                )
            ):
                actifs += 1

        if actifs < 2:
            raisons.append("Partants actifs insuffisants")

    source = course.get("source")

    if (
        not isinstance(source, str)
        or not source.startswith("https://")
    ):
        raisons.append("URL source absente ou invalide")

    return len(raisons) == 0, raisons


def collecte_du_jour(erreurs):
    chemin = DATA / "collecte.json"

    if not chemin.is_file():
        erreurs.append("Collecte PMU absente")
        return {}, []

    try:
        collecte = lire(chemin)

        if not isinstance(collecte, dict):
            raise ValueError("Collecte invalide")

        if collecte.get("date") != maintenant().date().isoformat():
            raise ValueError("Collecte d'une autre date")

        if collecte.get("statut") not in (
            "OK", "PARTIEL", "AUCUNE_COURSE"
        ):
            raise ValueError("Statut collecte invalide")

        courses = collecte.get("courses")

        if not isinstance(courses, list):
            raise ValueError("Courses absentes")

        for erreur in collecte.get("erreurs", []):
            erreurs.append(str(erreur))

        return collecte, courses

    except (OSError, ValueError, TypeError) as exc:
        erreurs.append(f"Collecte inexploitable: {exc}")
        return {}, []


def empreintes_archives():
    resultat = {}

    for dossier in (
        "figes", "pv", "audits", "journaux"
    ):
        racine = DATA / dossier

        if not racine.exists():
            continue

        for chemin in sorted(racine.rglob("*")):
            if chemin.is_file():
                resultat[
                    str(chemin.relative_to(DATA))
                ] = hashlib.sha256(
                    chemin.read_bytes()
                ).hexdigest()

    return resultat


def publier():
    DATA.mkdir(parents=True, exist_ok=True)
    FIGES.mkdir(parents=True, exist_ok=True)

    avant = empreintes_archives()
    erreurs = []
    instant = maintenant()

    collecte, brutes = collecte_du_jour(erreurs)

    courses = []
    pv_nouveaux = []

    for course in brutes:
        if not isinstance(course, dict):
            erreurs.append("Course non objet")
            continue

        cid = course.get("id") or course.get("course_id")

        if not cid:
            erreurs.append("Course sans identifiant")
            continue

        cid = str(cid)
        ligne = dict(course)
        ligne["id"] = cid
        ligne["moteurs"] = []
        ligne["statut"] = "NON_ANALYSEE"

        admissible, raisons = controle_avant_depart(
            course, instant
        )

        if admissible:
            try:
                analyse = analyser_moteurs(
                    course, instant
                )

                moteurs = normaliser_moteurs(analyse)

                ligne["moteurs"] = moteurs
                ligne["analyse_a"] = analyse.get(
                    "analyse_a"
                )

                ligne["statut"] = (
                    "ANALYSE_INDICATIVE"
                    if any(
                        m.get("ordre_espere")
                        for m in moteurs
                    )
                    else "DONNEES_INSUFFISANTES"
                )

            except (
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
            ) as exc:
                erreurs.append(
                    f"{cid}: analyse impossible: {exc}"
                )
                ligne["statut"] = "ERREUR_ANALYSE"

        else:
            ligne["statut"] = "CONTROLE_NON_SATISFAIT"
            ligne["difficultes"] = raisons

        # Un PV est une photographie de l'analyse.
        # Il ne devient jamais automatiquement un FIGE.
        if ligne["moteurs"]:
            pv_nouveaux.append({
                "pv_id": (
                    "ANALYSE-"
                    + cid
                    + "-"
                    + instant.strftime("%Y%m%dT%H%M%S%f")
                ),
                "course_id": cid,
                "type": "PV_ANALYSE",
                "statut": "PV_ANALYSE_NON_FIGE",
                "cree_a": instant.isoformat(),
                "depart": course.get("depart"),
                "source": course.get("source"),
                "moteurs": ligne["moteurs"],
                "avertissement": (
                    "Analyse indicative. "
                    "Aucun FIGE officiel cree."
                ),
            })

        courses.append(ligne)

    figes = charger_figes(erreurs)
    audits = charger_audits(erreurs, figes)

    index = {
        str(c["id"]): c
        for c in courses
    }

    for document in figes:
        try:
            rapport = rapport_fige(document)
            cid = str(rapport["course_id"])
            integrite = controle_fige(
                document
            )["integrite"]

            if cid not in index:
                ligne = {
                    "id": cid,
                    "hippodrome": rapport.get(
                        "hippodrome"
                    ),
                    "depart": rapport.get("depart"),
                    "source": rapport.get("source"),
                    "moteurs": [],
                    "statut": "FIGE_HISTORIQUE",
                }
                courses.append(ligne)
                index[cid] = ligne

            index[cid].setdefault(
                "figes_historiques", []
            ).append({
                "sha256": document.get("sha256"),
                "integrite": integrite,
                "moteurs": rapport.get("moteurs", []),
                "fige_a": rapport.get("fige_a"),
            })

        except (ValueError, TypeError, KeyError) as exc:
            erreurs.append(
                f"FIGE historique: {exc}"
            )

    pronostics = []

    for course in courses:
        for moteur in course.get("moteurs", []):
            entree = dict(moteur)
            entree.update({
                "course_id": course.get("id"),
                "hippodrome": course.get("hippodrome"),
                "depart": course.get("depart"),
                "statut_course": course.get("statut"),
            })
            pronostics.append(entree)

    pv = uniques(
        archives("pv", erreurs)
        + collection("pv", "pv", erreurs)
        + pv_nouveaux,
        "pv_id"
    )

    analyses_count = sum(
        c.get("statut") == "ANALYSE_INDICATIVE"
        for c in courses
    )

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": VERSION,
        "generated_at_paris": maintenant().isoformat(),
        "source_donnees": collecte.get("source"),
        "moteurs_actifs": list(MOTEURS),
        "courses_collectees": len(brutes),
        "courses_count": len(courses),
        "analyses_count": analyses_count,
        "pronostics_count": len(pronostics),
        "pv_count": len(pv),
        "figes_count": len(figes),
        "audits_count": len(audits),
        "nouveaux_figes": 0,
        "status": (
            "PUBLICATION_PARTIELLE"
            if erreurs
            else "ANALYSES_DISPONIBLES"
            if analyses_count
            else "AUCUNE_ANALYSE"
        ),
        "difficultes": [
            {
                "moteur": "SYSTEME",
                "difficulte": erreur,
            }
            for erreur in erreurs
        ],
        "avertissement": (
            "Analyses heuristiques non validees. "
            "Aucun nouveau FIGE cree. "
            "Les archives originales sont conservees. "
            "Les sources PMU ne sont pas reverifiees "
            "en direct par ce module."
        ),
    }

    if empreintes_archives() != avant:
        raise RuntimeError(
            "Archives modifiees avant publication"
        )

    publications = (
        ("courses", courses),
        ("pronostics", pronostics),
        ("pv", pv),
        ("figes", figes),
        ("audits", audits),
    )

    for nom, objets in publications:
        ecrire(
            DATA / f"publication_{nom}.json",
            {nom: objets}
        )

    ecrire(
        DATA / "publication_rapport.json",
        rapport
    )

    ecrire(
        DATA / "rapport_actions.json",
        rapport
    )

    if empreintes_archives() != avant:
        raise RuntimeError(
            "Archives historiques modifiees"
        )

    print(
        json.dumps(
            rapport,
            ensure_ascii=False,
            indent=2
        )
    )

    return rapport


def main():
    return publier()


if __name__ == "__main__":
    main()
