#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publication X1000 PHOENIX pour GitHub Pages."""
import json
from pathlib import Path

from phoenix import (
    DATA, analyser, auditer, ecrire, figer,
    lire, maintenant, verifier_fige,
    verifier_source
)

def charger_collection(nom, cle):
    chemin = DATA / (nom + ".json")
    if not chemin.exists():
        return []

    objet = lire(chemin)

    if isinstance(objet, dict):
        if isinstance(objet.get(cle), list):
            return objet[cle]
        # Ancien stockage indexe par course.
        return [
            dict(v, course_id=v.get("course_id", k))
            for k, v in objet.items()
            if isinstance(v, dict)
        ]

    if isinstance(objet, list):
        return objet

    raise ValueError("Collection invalide: " + nom)

def documents(dossier):
    resultat = []
    for chemin in sorted((DATA / dossier).glob("*.json")):
        try:
            objet = lire(chemin)
            if dossier == "figes":
                verifier_fige(objet)
            resultat.append(objet)
        except (ValueError, KeyError, TypeError) as exc:
            print("Document refuse:", chemin, exc)
    return resultat

def erreur(rapport, message):
    rapport["difficultes"].append({
        "moteur": "SYSTEME",
        "difficulte": str(message)
    })

def normaliser_moteur(m):
    return {
        "moteur": m.get("moteur"),
        "gagnant_espere": m.get("gagnant_espere"),
        "meilleur_place": m.get("meilleur_place"),
        "ordre_espere": m.get("ordre_espere", []),
        "pari_retenu": m.get("pari_retenu"),
        "qualification": m.get("qualification", "NON_VERIFIE"),
        "validation": m.get("validation", "NON_VERIFIE"),
        "heure_paris": m.get("heure_paris")
    }

def normaliser_course(c):
    if not isinstance(c, dict):
        return None

    return {
        "id": c.get("id") or c.get("course_id"),
        "hippodrome": c.get("hippodrome"),
        "depart": c.get("depart"),
        "nombre_partants": c.get("nombre_partants"),
        "source": c.get("source"),
        "statut": c.get("statut", "NON_VERIFIE"),
        "moteurs": [
            normaliser_moteur(m)
            for m in c.get("moteurs", [])
            if isinstance(m, dict)
        ]
    }

def main():
    instant = maintenant()

    rapport = {
        "status": "🟡 EN ATTENTE DE DONNEES",
        "generated_at_paris": instant.isoformat(),
        "mode": "DONNEES_SOURCEES_UNIQUEMENT",
        "difficultes": [],
        "source_donnees": None,
        "moteurs": []
    }

    courses = []
    pv = []
    figes = []
    audits = []

    try:
        courses = [
            x for x in (
                normaliser_course(c)
                for c in charger_collection("courses", "courses")
            )
            if x is not None
        ]
    except (ValueError, TypeError, KeyError) as exc:
        erreur(rapport, "Courses: " + str(exc))

    try:
        pv = charger_collection("pv", "pv")
    except (ValueError, TypeError, KeyError) as exc:
        erreur(rapport, "PV: " + str(exc))

    try:
        anciens = charger_collection("figes", "figes")
        for f in anciens:
            # Les anciens FIGES du collecteur sont
            # experimentaux et ne doivent pas etre
            # annonces comme FIGES verifies phoenix.py.
            if f.get("statut") == "FIGE_AVANT_DEPART":
                try:
                    verifier_fige(f)
                    figes.append(f)
                except (ValueError, KeyError, TypeError):
                    pass
    except (ValueError, TypeError, KeyError) as exc:
        erreur(rapport, "FIGES: " + str(exc))

    figes_connus = {f["sha256"] for f in figes}

    for f in documents("figes"):
        if f["sha256"] not in figes_connus:
            figes.append(f)
            figes_connus.add(f["sha256"])

    # Analyse des notes uniquement si un fichier
    # course.json correctement source est disponible.
    entree = DATA / "course.json"

    if entree.exists():
        try:
            course = lire(entree)
            analyse = analyser(course)

            rapport["source_donnees"] = analyse["source"]
            rapport["moteurs"] = analyse["moteurs"]

            cid = analyse["course_id"]

            ancien = next(
                (f for f in figes
                 if f["rapport"]["course_id"] == cid),
                None
            )

            if ancien is None:
                nouveau = figer(analyse)
                if nouveau is not None:
                    figes.append(nouveau)
                    figes_connus.add(nouveau["sha256"])

            courses = [
                c for c in courses if c["id"] != cid
            ]

            courses.append({
                "id": cid,
                "hippodrome": analyse["hippodrome"],
                "depart": analyse["depart"],
                "nombre_partants": analyse["nombre_partants"],
                "source": analyse["source"],
                "statut": analyse["statut"],
                "moteurs": analyse["moteurs"]
            })

        except (ValueError, TypeError, KeyError) as exc:
            erreur(
                rapport,
                "Analyse course.json refusee: " + str(exc)
            )
    else:
        erreur(rapport, "data/course.json absent")

    # Audit uniquement a partir d'une arrivee
    # explicitement marquee definitive et sourcee.
    arrivees_path = DATA / "arrivees_officielles.json"

    if arrivees_path.exists():
        try:
            source = lire(arrivees_path)
            entrees = source.get("courses", [])

            for arrivee in entrees:
                if not isinstance(arrivee, dict):
                    continue

                if not verifier_source(arrivee.get("source")):
                    continue

                correspondant = next(
                    (
                        f for f in figes
                        if f["rapport"]["course_id"]
                        == arrivee.get("course_id")
                    ),
                    None
                )

                if correspondant is None:
                    continue

                if arrivee.get("statut") != "definitive":
                    continue

                bilan = auditer(correspondant, arrivee)
                chemin = DATA / "audits" / (
                    bilan["course_id"].replace("/", "_")
                    + ".json"
                )

                if not chemin.exists():
                    ecrire(chemin, bilan)

        except (ValueError, TypeError, KeyError) as exc:
            erreur(rapport, "Audits: " + str(exc))

    # Les audits deja publies sont conserves.
    try:
        audits = charger_collection("audits", "audits")
    except (ValueError, TypeError, KeyError) as exc:
        erreur(rapport, "Audits historiques: " + str(exc))

    audits_ids = {
        a.get("course_id") for a in audits
        if isinstance(a, dict)
    }

    for a in documents("audits"):
        if a.get("course_id") not in audits_ids:
            audits.append(a)
            audits_ids.add(a.get("course_id"))

    rapport["courses_count"] = len(courses)
    rapport["pv_count"] = len(pv)
    rapport["figes_count"] = len(figes)
    rapport["audits_count"] = len(audits)

    if figes:
        rapport["status"] = "🟢 FIGES VERIFIES"
    elif courses:
        rapport["status"] = "🟡 COURSES CHARGEES"
    else:
        rapport["status"] = "🟡 DONNEES INSUFFISANTES"

    # Collections compatibles avec index.html.
    # Ne pas reecrire les fichiers historiques du
    # collecteur : publier des vues separees.
    ecrire(DATA / "publication_courses.json", {
        "courses": courses
    })
    ecrire(DATA / "publication_pv.json", {
        "pv": pv
    })
    ecrire(DATA / "publication_figes.json", {
        "figes": figes
    })
    ecrire(DATA / "publication_audits.json", {
        "audits": audits
    })
    ecrire(DATA / "publication_rapport.json", rapport)

    print(json.dumps(
        rapport, ensure_ascii=False, indent=2
    ))

if __name__ == "__main__":
    main()
