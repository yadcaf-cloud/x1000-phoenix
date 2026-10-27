#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX — PUBLICATION CORRIGÉE
Moteurs M1 à M5
Courses, PV, FIGÉS, audits et rapport.
Aucune donnée hippique inventée.
"""

import json
import datetime as dt
from pathlib import Path

from phoenix import (
    DATA, analyser, auditer, ecrire, figer,
    lire, maintenant, verifier_fige,
    verifier_source
)

DATA = Path(DATA)
DATA.mkdir(parents=True, exist_ok=True)

MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def collection(nom, cle):
    chemin = DATA / (nom + ".json")

    if not chemin.exists():
        return []

    objet = lire(chemin)

    if isinstance(objet, list):
        return objet

    if isinstance(objet, dict):
        if isinstance(objet.get(cle), list):
            return objet[cle]

        resultat = []
        for identifiant, valeur in objet.items():
            if isinstance(valeur, dict):
                item = dict(valeur)
                item.setdefault("course_id", identifiant)
                resultat.append(item)
        return resultat

    raise ValueError("Collection invalide : " + nom)


def documents(dossier):
    resultat = []
    chemin = DATA / dossier

    if not chemin.exists():
        return resultat

    for fichier in sorted(chemin.glob("*.json")):
        try:
            objet = lire(fichier)

            if dossier == "figes":
                verifier_fige(objet)

            if isinstance(objet, dict):
                resultat.append(objet)

        except (ValueError, TypeError, KeyError) as exc:
            print("Document rejeté :", fichier, exc)

    return resultat


def normaliser_course(course):
    if not isinstance(course, dict):
        return None

    identifiant = course.get("id") or course.get("course_id")

    if not identifiant:
        return None

    moteurs = course.get("moteurs", [])

    if not isinstance(moteurs, list):
        moteurs = []

    return {
        "id": identifiant,
        "hippodrome": course.get("hippodrome"),
        "depart": course.get("depart"),
        "nombre_partants": course.get("nombre_partants"),
        "source": course.get("source"),
        "statut": course.get("statut", "NON_VERIFIE"),
        "moteurs": moteurs
    }


def identite_fige(fige):
    return fige.get("sha256")


def ajouter_unique(elements, objet, cle):
    valeur = objet.get(cle)

    if valeur is None:
        return

    if not any(
        isinstance(x, dict) and x.get(cle) == valeur
        for x in elements
    ):
        elements.append(objet)


def publier(nom, cle, valeurs):
    ecrire(
        DATA / ("publication_" + nom + ".json"),
        {cle: valeurs}
    )


def main():
    instant = maintenant()

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": "PUBLICATION_CORRIGEE",
        "status": "🟡 EN ATTENTE DE DONNEES",
        "generated_at_paris": instant.isoformat(),
        "mode": "DONNEES_SOURCEES_UNIQUEMENT",
        "moteurs_actifs": list(MOTEURS),
        "source_donnees": None,
        "moteurs": [],
        "difficultes": []
    }

    courses = []
    pv = []
    figes = []
    audits = []

    def difficulte(message):
        rapport["difficultes"].append({
            "moteur": "SYSTEME",
            "difficulte": str(message)
        })

    # 1. COURSES HISTORIQUES
    try:
        for item in collection("courses", "courses"):
            course = normaliser_course(item)
            if course:
                courses.append(course)
    except (ValueError, TypeError, KeyError) as exc:
        difficulte("Courses : " + str(exc))

    # 2. PROCES-VERBAUX
    try:
        pv = [
            x for x in collection("pv", "pv")
            if isinstance(x, dict)
        ]
    except (ValueError, TypeError, KeyError) as exc:
        difficulte("PV : " + str(exc))

    # 3. FIGÉS AVEC CONTRÔLE SHA256
    for document in documents("figes"):
        ajouter_unique(figes, document, "sha256")

    try:
        for document in collection("figes", "figes"):
            if not isinstance(document, dict):
                continue
            try:
                verifier_fige(document)
                ajouter_unique(figes, document, "sha256")
            except (ValueError, TypeError, KeyError):
                continue
    except (ValueError, TypeError, KeyError) as exc:
        difficulte("FIGÉS : " + str(exc))

    # 4. ANALYSE DE LA COURSE SOURCÉE
    fichier_course = DATA / "course.json"

    if fichier_course.exists():
        try:
            entree = lire(fichier_course)
            analyse = analyser(entree)

            rapport["source_donnees"] = analyse["source"]
            rapport["moteurs"] = analyse["moteurs"]

            identifiant = analyse["course_id"]

            courses = [
                c for c in courses
                if c["id"] != identifiant
            ]

            courses.append({
                "id": identifiant,
                "hippodrome": analyse["hippodrome"],
                "depart": analyse["depart"],
                "nombre_partants": analyse["nombre_partants"],
                "source": analyse["source"],
                "statut": analyse["statut"],
                "moteurs": analyse["moteurs"]
            })

            # FIGÉ uniquement avant départ,
            # dans la fenêtre définie par phoenix.py.
            existant = any(
                f.get("rapport", {}).get("course_id")
                == identifiant
                for f in figes
            )

            if not existant:
                nouveau = figer(analyse)

                if nouveau is not None:
                    verifier_fige(nouveau)
                    ajouter_unique(
                        figes, nouveau, "sha256"
                    )

        except (
            ValueError, TypeError, KeyError,
            OSError
        ) as exc:
            difficulte(
                "Analyse refusée : " + str(exc)
            )
    else:
        difficulte(
            "data/course.json absent : "
            "aucune analyse nouvelle possible"
        )

    # 5. AUDITS APRÈS COURSE
    arrivees = DATA / "arrivees_officielles.json"

    if arrivees.exists():
        try:
            contenu = lire(arrivees)

            for arrivee in contenu.get("courses", []):
                if not isinstance(arrivee, dict):
                    continue

                if arrivee.get("statut") != "definitive":
                    continue

                if not verifier_source(
                    arrivee.get("source")
                ):
                    continue

                for document in figes:
                    identifiant = document.get(
                        "rapport", {}
                    ).get("course_id")

                    if identifiant != arrivee.get(
                        "course_id"
                    ):
                        continue

                    bilan = auditer(
                        document, arrivee
                    )

                    fichier = (
                        DATA / "audits" /
                        (str(identifiant).replace(
                            "/", "_"
                        ) + ".json")
                    )

                    if not fichier.exists():
                        ecrire(fichier, bilan)

        except (
            ValueError, TypeError, KeyError,
            OSError, AttributeError
        ) as exc:
            difficulte(
                "Audit refusé : " + str(exc)
            )

    # 6. AUDITS CONSERVÉS
    try:
        for audit in collection("audits", "audits"):
            if isinstance(audit, dict):
                ajouter_unique(
                    audits, audit, "course_id"
                )
    except (ValueError, TypeError, KeyError) as exc:
        difficulte("Audits historiques : " + str(exc))

    for audit in documents("audits"):
        ajouter_unique(
            audits, audit, "course_id"
        )

    # 7. ÉTAT DU SYSTÈME
    rapport["courses_count"] = len(courses)
    rapport["pv_count"] = len(pv)
    rapport["figes_count"] = len(figes)
    rapport["audits_count"] = len(audits)

    if figes:
        rapport["status"] = "🟢 FIGÉS VÉRIFIÉS"
    elif courses:
        rapport["status"] = "🟡 COURSES DISPONIBLES"
    else:
        rapport["status"] = "🟡 DONNÉES INSUFFISANTES"

    # 8. PUBLICATION POUR INDEX.HTML
    publier("courses", "courses", courses)
    publier("pv", "pv", pv)
    publier("figes", "figes", figes)
    publier("audits", "audits", audits)

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
