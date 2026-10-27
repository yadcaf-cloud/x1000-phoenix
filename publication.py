#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Publication des donnees reelles."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import lire, ecrire, verifier_fige

DATA = Path("data")
PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def maintenant():
    return dt.datetime.now(PARIS).isoformat()


def charger(nom, cle):
    chemin = DATA / (nom + ".json")
    if not chemin.exists():
        return []
    objet = lire(chemin)
    if isinstance(objet, list):
        return objet
    if isinstance(objet, dict):
        valeur = objet.get(cle, [])
        if isinstance(valeur, list):
            return valeur
    return []


def documents(dossier, erreurs, verifier=False):
    resultat = []
    chemin = DATA / dossier
    for fichier in sorted(chemin.glob("*.json")):
        try:
            objet = lire(fichier)
            if not isinstance(objet, dict):
                raise ValueError("Document non objet")
            if verifier:
                verifier_fige(objet)
            resultat.append(objet)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            erreurs.append(f"{fichier}: {exc}")
    return resultat


def unique(objets, cle):
    resultat = []
    vus = set()
    for objet in objets:
        if not isinstance(objet, dict):
            continue
        valeur = objet.get(cle)
        if valeur is None:
            continue
        if valeur not in vus:
            vus.add(valeur)
            resultat.append(objet)
    return resultat


def sauvegarder(nom, cle, objets):
    ecrire(DATA / f"publication_{nom}.json", {cle: objets})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    erreurs = []

    collecte = {}
    chemin = DATA / "rapport.json"
    if chemin.exists():
        try:
            collecte = lire(chemin)
            if not isinstance(collecte, dict):
                collecte = {}
        except (ValueError, OSError) as exc:
            erreurs.append(f"Rapport collecte: {exc}")

    courses = charger("courses", "courses")
    courses = [
        c for c in courses
        if isinstance(c, dict) and
        (c.get("id") or c.get("course_id"))
    ]

    figes = documents("figes", erreurs, verifier=True)

    # Importer uniquement les FIGES authentifies.
    for objet in charger("figes", "figes"):
        try:
            verifier_fige(objet)
            figes.append(objet)
        except (ValueError, KeyError, TypeError) as exc:
            erreurs.append(f"FIGE rejete: {exc}")

    figes = unique(figes, "sha256")

    audits = documents("audits", erreurs)
    audits += charger("audits", "audits")
    audits = unique(audits, "course_id")

    # PV historiques conserves.
    pv = charger("pv", "pv")
    pv = [p for p in pv if isinstance(p, dict)]

    # PV descriptifs des analyses existantes.
    # Ils ne sont PAS des FIGES.
    for course in courses:
        moteurs = course.get("moteurs", [])
        if not isinstance(moteurs, list) or not moteurs:
            continue

        identifiant = course.get("id") or course.get("course_id")
        noms = {m.get("moteur") for m in moteurs
                if isinstance(m, dict)}

        if not set(MOTEURS).issubset(noms):
            continue

        cle = f"ANALYSE-{identifiant}"
        if any(p.get("pv_id") == cle for p in pv):
            continue

        pv.append({
            "pv_id": cle,
            "course_id": identifiant,
            "statut": "PV_ANALYSE_NON_FIGE",
            "source": course.get("source"),
            "depart": course.get("depart"),
            "moteurs": moteurs,
            "cree_a": (
                course.get("analyse_a")
                or course.get("actualise")
            ),
            "precision": (
                "PV descriptif. Ne prouve pas "
                "un FIGE avant depart."
            )
        })

    # Recuperer les analyses conservees dans
    # les FIGES authentifies, sans les recalculer.
    index = {
        c.get("id") or c.get("course_id"): c
        for c in courses
    }

    for document in figes:
        analyse = document.get("rapport", {})
        cid = analyse.get("course_id")
        if not cid:
            continue

        if cid not in index:
            course = {
                "id": cid,
                "hippodrome": analyse.get("hippodrome"),
                "depart": analyse.get("depart"),
                "nombre_partants": analyse.get("nombre_partants"),
                "source": analyse.get("source"),
                "moteurs": analyse.get("moteurs", []),
                "statut": "FIGE_VERIFIE"
            }
            courses.append(course)
            index[cid] = course
        else:
            index[cid]["moteurs"] = analyse.get("moteurs", [])
            index[cid]["statut"] = "FIGE_VERIFIE"

    analyses = sum(
        bool(c.get("moteurs"))
        for c in courses
    )

    if not courses:
        statut = "DONNEES_INDISPONIBLES"
    elif analyses == 0:
        statut = "COURSES_SANS_ANALYSES"
    elif erreurs:
        statut = "PUBLICATION_PARTIELLE"
    else:
        statut = "PUBLICATION_OK"

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": "PUBLICATION-4.0",
        "status": statut,
        "generated_at_paris": maintenant(),
        "moteurs_actifs": list(MOTEURS),
        "courses_count": len(courses),
        "analyses_count": analyses,
        "pv_count": len(pv),
        "figes_count": len(figes),
        "audits_count": len(audits),
        "collecte": collecte,
        "difficultes": [
            {"moteur": "SYSTEME", "difficulte": e}
            for e in erreurs
        ],
        "avertissement": (
            "Aucune donnee ou arrivee inventee. "
            "Les FIGES sont uniquement ceux "
            "authentifies par phoenix.py."
        )
    }

    sauvegarder("courses", "courses", courses)
    sauvegarder("pv", "pv", pv)
    sauvegarder("figes", "figes", figes)
    sauvegarder("audits", "audits", audits)
    ecrire(DATA / "publication_rapport.json", rapport)

    print(json.dumps(rapport, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
