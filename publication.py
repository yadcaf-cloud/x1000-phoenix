#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publication X1000 PHOENIX pour GitHub Pages."""

import datetime as dt
import json
from pathlib import Path

from phoenix import (
    DATA, PARIS, analyser, auditer, date_paris,
    ecrire, figer, identifiant, lire,
    maintenant, verifier_fige
)

def fichiers(dossier):
    return sorted((DATA / dossier).glob("*.json"))

def charger_collection(dossier):
    resultat = []
    for path in fichiers(dossier):
        try:
            objet = lire(path)
            if dossier == "figes":
                verifier_fige(objet)
            resultat.append(objet)
        except (ValueError, KeyError, TypeError) as e:
            print(f"Fichier ignoré {path}: {e}")
    return resultat

def ajouter_erreur(rapport, message):
    rapport["difficultes"].append({
        "moteur": "SYSTEME",
        "difficulte": str(message)
    })

def main():
    instant = maintenant()
    rapport = {
        "status": "🟡 EN ATTENTE DE DONNÉES",
        "generated_at_paris": instant.isoformat(),
        "mode": "DONNEES_VERIFIEES_UNIQUEMENT",
        "moteurs": [],
        "difficultes": [],
        "source_donnees": None
    }

    courses = []
    entree = DATA / "course.json"

    if entree.exists():
        try:
            course = lire(entree)
            cid = str(course.get("id", ""))

            if cid.startswith("DEMO") or not course.get("source"):
                ajouter_erreur(
                    rapport,
                    "Course de démonstration ou source absente"
                )
            else:
                analyse = analyser(course)
                depart = date_paris(analyse["depart"])
                rapport["source_donnees"] = analyse["source"]

                chemin = DATA / "figes" / (
                    identifiant(cid) + ".json"
                )

                complet = all(
                    m["validation"] == "INDICATIF"
                    for m in analyse["moteurs"]
                )

                minutes = (
                    depart - instant
                ).total_seconds() / 60

                if (
                    not chemin.exists()
                    and complet
                    and 0 < minutes <= 15
                ):
                    figer(analyse, chemin, instant)

                document = None
                if chemin.exists():
                    document = lire(chemin)
                    verifier_fige(document)

                base = (
                    document["rapport"]
                    if document else analyse
                )

                statut = (
                    "🟢 FIGÉ"
                    if document else
                    "🟡 EN ÉTUDE"
                    if instant < depart and complet else
                    "🔴 NON VALIDÉ"
                )

                lignes = []
                for m in base["moteurs"]:
                    lignes.append({
                        **m,
                        "validation": (
                            "FIGE" if document
                            else m["validation"]
                        ),
                        "heure_fige": (
                            document["fige_a"]
                            if document else None
                        ),
                        "sha256": (
                            document["sha256"]
                            if document else None
                        )
                    })

                courses.append({
                    "id": cid,
                    "hippodrome": base["hippodrome"],
                    "depart": base["depart"],
                    "source": base["source"],
                    "nombre_partants": base["nombre_partants"],
                    "non_partants": base["non_partants"],
                    "statut": statut,
                    "moteurs": lignes
                })
                rapport["moteurs"] = lignes
                rapport["course_id"] = cid
                rapport["status"] = statut

                if document:
                    chemin_pv = DATA / "pv" / (
                        identifiant(cid) + ".json"
                    )
                    if not chemin_pv.exists():
                        ecrire(chemin_pv, {
                            "course_id": cid,
                            "statut": "PV_FIGE",
                            "fige_a": document["fige_a"],
                            "sha256": document["sha256"],
                            "moteurs": lignes
                        })

        except (ValueError, KeyError, TypeError, OSError) as e:
            rapport["status"] = "🔴 ERREUR D'ANALYSE"
            ajouter_erreur(rapport, e)
    else:
        ajouter_erreur(rapport, "data/course.json absent")

    # Auditer uniquement les arrivées fournies et vérifiées.
    for path in fichiers("arrivees"):
        try:
            arrivee = lire(path)
            cid = identifiant(arrivee["course_id"])
            chemin_fige = DATA / "figes" / (cid + ".json")
            chemin_audit = DATA / "audits" / (cid + ".json")

            if chemin_fige.exists() and not chemin_audit.exists():
                resultat = auditer(
                    lire(chemin_fige), arrivee
                )
                ecrire(chemin_audit, resultat)
        except (ValueError, KeyError, TypeError, OSError) as e:
            ajouter_erreur(rapport, f"{path.name}: {e}")

    pv = charger_collection("pv")
    figes = charger_collection("figes")
    audits = charger_collection("audits")

    rapport["pv_count"] = len(pv)
    rapport["figes_count"] = len(figes)
    rapport["audits_count"] = len(audits)
    rapport["courses_count"] = len(courses)

    ecrire(DATA / "courses.json", {"courses": courses})
    ecrire(DATA / "pv.json", {"pv": pv})
    ecrire(DATA / "figes.json", {"figes": figes})
    ecrire(DATA / "audits.json", {"audits": audits})
    ecrire(DATA / "rapport.json", rapport)
    ecrire(DATA / "latest.json", rapport)

    print(json.dumps(rapport, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
