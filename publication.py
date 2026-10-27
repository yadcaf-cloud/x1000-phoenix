#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Adaptateur sécurisé pour GitHub Pages."""

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import analyser, lire, ecrire

PARIS = ZoneInfo("Europe/Paris")
DATA = Path("data")


def maintenant():
    return dt.datetime.now(PARIS).isoformat(timespec="seconds")


def fichiers(dossier):
    return sorted((DATA / dossier).glob("*.json"))


def compter(dossier):
    return len(fichiers(dossier))


def main():
    rapport_public = {
        "status": "🟡 EN ATTENTE DE DONNÉES",
        "generated_at_paris": maintenant(),
        "moteurs": [],
        "difficultes": [],
        "pv_count": compter("pv"),
        "figes_count": compter("figes"),
        "audits_count": compter("audits"),
        "source_donnees": None,
        "mode": "DONNEES_VERIFIEES_UNIQUEMENT",
    }

    entree = DATA / "course.json"

    if not entree.exists():
        rapport_public["difficultes"].append({
            "moteur": "SYSTEME",
            "difficulte": "Fichier course.json absent",
            "consequence": "Analyse impossible",
            "solution": "Fournir des données vérifiées",
            "question": "Quelle source utiliser ?",
        })
    else:
        try:
            course = lire(entree)
            rapport = analyser(course)
            depart = dt.datetime.fromisoformat(
                rapport["depart"]
            )
            avant_depart = dt.datetime.now(PARIS) < depart
            source = rapport.get("source")

            rapport_public["source_donnees"] = source
            rapport_public["course_id"] = rapport["course_id"]
            rapport_public["depart"] = rapport["depart"]

            ident = "".join(
                c if c.isalnum() or c in "-_" else "_"
                for c in str(rapport["course_id"])
            )

            chemin_fige = DATA / "figes" / (ident + ".json")
            figes_valides = {}

            if chemin_fige.exists():
                import hashlib
                document = lire(chemin_fige)
                contenu = {
                    k: v for k, v in document.items()
                    if k != "sha256"
                }
                brut = json.dumps(
                    contenu,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")

                empreinte = hashlib.sha256(brut).hexdigest()
                horodatage = dt.datetime.fromisoformat(
                    document["fige_a"]
                )

                if (
                    empreinte == document.get("sha256")
                    and horodatage < depart
                    and horodatage.tzinfo is not None
                    and document.get("statut") == "FIGE_AVANT_DEPART"
                    and document.get("rapport", {}).get("course_id")
                    == rapport["course_id"]
                ):
                    figes_valides = {
                        m["moteur"]: m
                        for m in document["rapport"]["moteurs"]
                    }

            for moteur in rapport["moteurs"]:
                nom = moteur["moteur"]
                fige = figes_valides.get(nom)
                base = fige or moteur

                complet = (
                    base["validation"] == "INDICATIF"
                    and bool(source)
                )

                ordre = base["ordre_espere"] if complet else []

                if fige:
                    validation = "🟢 FIGÉ"
                elif avant_depart and complet:
                    validation = "🟡 EN ÉTUDE"
                else:
                    validation = "🔴 NON VALIDÉ"

                rapport_public["moteurs"].append({
                    "moteur": nom,
                    "course": rapport["course_id"],
                    "gagnant": (
                        base["gagnant_espere"] if ordre else None
                    ),
                    "place": (
                        base["meilleur_place"] if ordre else None
                    ),
                    "ordre": ordre,
                    "pari": "AUCUN - analyse indicative",
                    "qualification": (
                        "🟢 VERT" if complet else "🟡 INCOMPLET"
                    ),
                    "validation": validation,
                    "heure_paris": (
                        base["heure_paris"] if fige
                        else maintenant()
                    ),
                })

            rapport_public["status"] = (
                "🟢 FIGÉ VÉRIFIÉ"
                if figes_valides
                else "🟡 ANALYSE INDICATIVE"
                if avant_depart and source
                else "🔴 DONNÉES NON VALIDÉES"
            )

        except (ValueError, KeyError, TypeError) as erreur:
            rapport_public["status"] = "🔴 ERREUR D'ANALYSE"
            rapport_public["difficultes"].append({
                "moteur": "SYSTEME",
                "difficulte": str(erreur),
                "consequence": "Aucun pronostic publié",
                "solution": "Corriger les données d'entrée",
                "question": "Les données sont-elles fiables ?",
            })

    ecrire(DATA / "latest.json", rapport_public)

    print(json.dumps(
        rapport_public,
        ensure_ascii=False,
        indent=2
    ))


if __name__ == "__main__":
    main()
      
