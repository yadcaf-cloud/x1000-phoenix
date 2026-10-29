#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — publication unifiée M1–M5, archives immuables.

Compatible avec pmu_engine.py, analyser_moteurs.py et phoenix.py existants.
Les analyses heuristiques ne sont jamais des paris FIGÉS.
"""

import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import DATA, FIGES, lire, ecrire, verifier_fige, controle_fige, rapport_fige
from analyser_moteurs import analyser as analyser_moteurs

PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")
VERSION = "PUBLICATION-UNIFIEE-7.2"


def maintenant():
    return dt.datetime.now(PARIS)


def collection(nom, cle, erreurs):
    chemin = DATA / (nom + ".json")
    if not chemin.is_file():
        return []
    try:
        objet = lire(chemin)
        if isinstance(objet, list):
            return objet
        if isinstance(objet, dict) and isinstance(objet.get(cle), list):
            return objet[cle]
        raise ValueError("collection JSON invalide")
    except (OSError, ValueError, TypeError) as exc:
        erreurs.append(f"{chemin}: {exc}")
        return []


def archives(dossier, erreurs, figes=False):
    resultat = []
    for chemin in sorted((DATA / dossier).glob("*.json")):
        try:
            document = lire(chemin)
            if not isinstance(document, dict):
                raise ValueError("document non objet")
            if figes:
                verifier_fige(document)
            resultat.append(document)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            erreurs.append(f"Archive non publiable {chemin}: {exc}")
    return resultat


def uniques(documents, cle):
    resultat, vus = [], set()
    for document in documents:
        if not isinstance(document, dict):
            continue
        valeur = document.get(cle)
        if not isinstance(valeur, (str, int)) or isinstance(valeur, bool):
            continue
        if valeur in vus:
            continue
        vus.add(valeur)
        resultat.append(document)
    return resultat


def charger_figes(erreurs):
    candidats = archives("figes", erreurs, figes=True)
    for document in collection("figes", "figes", erreurs):
        try:
            verifier_fige(document)
            candidats.append(document)
        except (ValueError, TypeError, KeyError) as exc:
            erreurs.append(f"FIGE historique non publiable: {exc}")
    return uniques(candidats, "sha256")


def charger_audits(erreurs, figes):
    empreintes = {
        f["sha256"].lower() for f in figes
        if isinstance(f.get("sha256"), str)
    }
    candidats = archives("audits", erreurs) + collection("audits", "audits", erreurs)
    resultat = []
    for audit in candidats:
        sha = audit.get("fige_sha256")
        source = audit.get("source_arrivee") or audit.get("source_resultat")
        arrivee = audit.get("arrivee_officielle")
        valide = (
            isinstance(sha, str) and sha.lower() in empreintes
            and audit.get("statut") == "AUDIT_EFFECTUE"
            and isinstance(source, str) and source.startswith("https://")
            and isinstance(arrivee, list) and len(arrivee) >= 5
            and all(type(n) is int and n > 0 for n in arrivee)
            and len(set(arrivee)) == len(arrivee)
        )
        if valide:
            resultat.append(audit)
        else:
            erreurs.append(f"Audit non publiable: {audit.get('course_id', '?')}")
    # Plusieurs audits de FIGÉS distincts pour une course restent possibles.
    return uniques(resultat, "fige_sha256")


def moteurs_analyse(analyse):
    bloc = analyse.get("moteurs", {})
    if not isinstance(bloc, dict):
        return []
    resultat = []
    for nom in MOTEURS:
        moteur = bloc.get(nom, {})
        if not isinstance(moteur, dict):
            continue
        ordre = moteur.get("ordre_arrivee_espere", [])
        if not isinstance(ordre, list) or not ordre:
            continue
        resultat.append({
            "moteur": nom,
            "gagnant_espere": moteur.get("gagnant_espere"),
            "meilleur_place": moteur.get("meilleur_place"),
            "ordre_espere": ordre[:5],
            "ordre_arrivee_espere": ordre[:5],
            "classement_complet": moteur.get("classement_complet", []),
            "qualification": "ETUDE_NON_VALIDEE",
            "validation": "NON_FIGE",
            "pari_retenu": None,
            "analyse_a": analyse.get("analyse_a"),
            "methode": "HEURISTIQUE_MUSIQUE",
        })
    return resultat


def moteurs_historiques(rapport):
    resultat = []
    for moteur in rapport.get("moteurs", []):
        if not isinstance(moteur, dict) or moteur.get("moteur") not in MOTEURS:
            continue
        copie = dict(moteur)
        ordre = (copie.get("ordre_arrivee_espere")
                 or copie.get("ordre_espere") or copie.get("ordre") or [])
        if not isinstance(ordre, list):
            ordre = []
        copie["ordre_espere"] = ordre[:5]
        copie["ordre_arrivee_espere"] = ordre[:5]
        resultat.append(copie)
    return resultat


def collecte_du_jour(erreurs):
    chemin = DATA / "collecte.json"
    if not chemin.is_file():
        erreurs.append("Collecte PMU absente : data/collecte.json")
        return {}, []
    try:
        collecte = lire(chemin)
        if not isinstance(collecte, dict):
            raise ValueError("collecte non objet")
        if collecte.get("date") != maintenant().date().isoformat():
            raise ValueError("collecte d'une autre date")
        if collecte.get("statut") not in ("OK", "PARTIEL", "AUCUNE_COURSE"):
            raise ValueError("collecte en echec")
        courses = collecte.get("courses")
        if not isinstance(courses, list):
            raise ValueError("liste de courses invalide")
        erreurs.extend(str(e) for e in collecte.get("erreurs", []))
        return collecte, courses
    except (OSError, ValueError, TypeError) as exc:
        erreurs.append(f"Collecte non exploitable: {exc}")
        return {}, []


def empreintes_archives():
    """Inventaire binaire pour détecter toute mutation d'archives pendant la publication."""
    resultat = {}
    for dossier in ("figes", "pv", "audits", "journaux"):
        for chemin in sorted((DATA / dossier).rglob("*")):
            if chemin.is_file():
                resultat[str(chemin.relative_to(DATA))] = hashlib.sha256(
                    chemin.read_bytes()
                ).hexdigest()
    return resultat


def publier():
    DATA.mkdir(parents=True, exist_ok=True)
    FIGES.mkdir(parents=True, exist_ok=True)
    avant = empreintes_archives()
    erreurs = []
    collecte, courses_brutes = collecte_du_jour(erreurs)
    instant = maintenant()
    courses, pv = [], []

    for course in courses_brutes:
        if not isinstance(course, dict) or not course.get("id"):
            erreurs.append("Course sans identifiant valide")
            continue
        cid = str(course["id"])
        ligne = dict(course)
        ligne["moteurs"] = []
        ligne["statut"] = "DONNEES_NON_ANALYSEES"
        depart = course.get("depart")
        avant_depart = False
        try:
            if isinstance(depart, str):
                horaire = dt.datetime.fromisoformat(depart.replace("Z", "+00:00"))
                avant_depart = horaire.tzinfo is not None and instant < horaire
        except ValueError:
            pass

        if (course.get("localisation_france_verifiee") is True
                and course.get("depart_verifie") is True
                and isinstance(course.get("partants"), list)
                and avant_depart):
            try:
                analyse = analyser_moteurs(course, instant)
                moteurs = moteurs_analyse(analyse)
                ligne["moteurs"] = moteurs
                ligne["analyse_a"] = analyse.get("analyse_a")
                ligne["statut"] = (
                    "ANALYSE_INDICATIVE" if moteurs else "DONNEES_INSUFFISANTES"
                )
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                erreurs.append(f"{cid}: analyse impossible: {exc}")
        elif not avant_depart:
            ligne["statut"] = "DEPART_PASSE_SANS_NOUVELLE_ANALYSE"
        elif course.get("localisation_france_verifiee") is not True:
            ligne["statut"] = "LOCALISATION_NON_VERIFIEE"
        else:
            ligne["statut"] = "DONNEES_INSUFFISANTES"

        pv.append({
            "pv_id": "ANALYSE-" + cid,
            "course_id": cid,
            "type": "PV_ANALYSE",
            "statut": "PV_ANALYSE_NON_FIGE",
            "cree_a": ligne.get("analyse_a", instant.isoformat()),
            "depart": depart,
            "source": course.get("source"),
            "moteurs": ligne["moteurs"],
            "avertissement": "Analyse indicative, aucun pari FIGE par ce PV",
        })
        courses.append(ligne)

    figes = charger_figes(erreurs)
    audits = charger_audits(erreurs, figes)
    index = {str(c["id"]): c for c in courses}
    for document in figes:
        try:
            rapport = rapport_fige(document)
            cid = str(rapport["course_id"])
            moteurs = moteurs_historiques(rapport)
            integrite = controle_fige(document)["integrite"]
            if cid not in index:
                ligne = {
                    "id": cid, "hippodrome": rapport.get("hippodrome"),
                    "depart": rapport.get("depart"), "source": rapport.get("source"),
                    "nombre_partants": rapport.get("nombre_partants"),
                    "moteurs": moteurs, "statut": "FIGE_HISTORIQUE",
                    "integrite": integrite,
                }
                courses.append(ligne)
                index[cid] = ligne
            else:
                index[cid]["moteurs"] = moteurs
                index[cid]["statut"] = "FIGE_HISTORIQUE"
                index[cid]["integrite"] = integrite
        except (ValueError, TypeError, KeyError) as exc:
            erreurs.append(f"FIGE historique non exploitable: {exc}")

    pronostics = []
    for course in courses:
        for moteur in course.get("moteurs", []):
            entree = dict(moteur)
            entree.update({
                "course_id": course.get("id"),
                "hippodrome": course.get("hippodrome"),
                "depart": course.get("depart"),
                "source": course.get("source"),
                "statut_course": course.get("statut"),
            })
            pronostics.append(entree)

    # Les anciens PV sont consultables, sans les transformer en FIGES.
    pv = uniques(pv + archives("pv", erreurs) + collection("pv", "pv", erreurs), "pv_id")
    analyses_count = sum(c.get("statut") == "ANALYSE_INDICATIVE" for c in courses)
    rapport = {
        "logiciel": "X1000 PHOENIX", "version": VERSION,
        "generated_at_paris": maintenant().isoformat(),
        "source_donnees": collecte.get("source"),
        "moteurs_actifs": list(MOTEURS),
        "courses_collectees": len(courses_brutes),
        "courses_count": len(courses),
        "analyses_count": analyses_count,
        "pronostics_count": len(pronostics),
        "pv_count": len(pv), "figes_count": len(figes),
        "audits_count": len(audits),
        "status": ("PUBLICATION_PARTIELLE" if erreurs else
                   "ANALYSES_DISPONIBLES" if analyses_count else
                   "AUCUNE_ANALYSE"),
        "difficultes": [{"moteur": "SYSTEME", "difficulte": x} for x in erreurs],
        "avertissement": (
            "Scores heuristiques non calibres. Aucun nouveau FIGE cree. "
            "Les originaux historiques ne sont pas modifies."
        ),
    }
    # Vérifier avant les écritures, puis après : les archives restent en lecture seule.
    if empreintes_archives() != avant:
        raise RuntimeError("Archives historiques modifiees pendant le traitement")
    for nom, cle, objets in (
        ("courses", "courses", courses),
        ("pronostics", "pronostics", pronostics),
        ("pv", "pv", pv),
        ("figes", "figes", figes),
        ("audits", "audits", audits),
    ):
        ecrire(DATA / f"publication_{nom}.json", {cle: objets})
    ecrire(DATA / "publication_rapport.json", rapport)
    ecrire(DATA / "rapport_actions.json", rapport)
    if empreintes_archives() != avant:
        raise RuntimeError("Archives historiques modifiees : publication non valide")
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return rapport


def main():
    return publier()


if __name__ == "__main__":
    main()
