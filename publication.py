#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Publication M1-M5 pour GitHub Pages.

Analyse des données disponibles, FIGÉS avant départ,
procès-verbaux, audits et rapports JSON.
Aucune donnée hippique manquante n'est inventée.
"""

import json

from phoenix import (
    DATA, analyser, auditer, date_paris,
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

        except (
            ValueError, KeyError, TypeError, OSError
        ) as erreur:
            print(
                f"Fichier ignoré {path}: {erreur}"
            )

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

    # =========================================
    # 1. CHARGEMENT ET ANALYSE DE LA COURSE
    # =========================================

    if entree.exists():
        try:
            course = lire(entree)
            cid = str(course.get("id", ""))

            if (
                not cid
                or cid.startswith("DEMO")
                or not course.get("source")
            ):
                ajouter_erreur(
                    rapport,
                    "Course de démonstration, "
                    "identifiant ou source absent"
                )

            else:
                analyse = analyser(course)
                depart = date_paris(
                    analyse["depart"]
                )

                rapport["source_donnees"] = (
                    analyse["source"]
                )

                chemin = DATA / "figes" / (
                    identifiant(cid) + ".json"
                )

                complet = (
                    len(analyse["moteurs"]) == 5
                    and all(
                        m["validation"] == "INDICATIF"
                        for m in analyse["moteurs"]
                    )
                )

                minutes = (
                    depart - maintenant()
                ).total_seconds() / 60

                # =================================
                # 2. FIGÉ AVANT DÉPART
                # =================================

                if (
                    not chemin.exists()
                    and complet
                    and 0 < minutes <= 15
                ):
                    try:
                        figer(
                            analyse,
                            chemin,
                            maintenant()
                        )
                        print(
                            f"FIGÉ créé : {cid}"
                        )

                    except (
                        ValueError,
                        FileExistsError,
                        OSError
                    ) as erreur:
                        ajouter_erreur(
                            rapport,
                            f"FIGÉ {cid}: {erreur}"
                        )

                # =================================
                # 3. VÉRIFICATION DU FIGÉ
                # =================================

                document = None

                if chemin.exists():
                    document = lire(chemin)
                    verifier_fige(document)

                    if (
                        document["rapport"]["course_id"]
                        != cid
                    ):
                        raise ValueError(
                            "FIGÉ associé à une "
                            "autre course"
                        )

                base = (
                    document["rapport"]
                    if document else analyse
                )

                if document:
                    statut = "🟢 FIGÉ"

                elif (
                    maintenant() < depart
                    and complet
                ):
                    statut = "🟡 EN ÉTUDE"

                else:
                    statut = "🔴 NON VALIDÉ"

                # =================================
                # 4. TABLEAU OFFICIEL M1-M5
                # =================================

                lignes = []

                for moteur in base["moteurs"]:
                    lignes.append({
                        **moteur,
                        "validation": (
                            "FIGE"
                            if document
                            else moteur["validation"]
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
                    "nombre_partants": (
                        base["nombre_partants"]
                    ),
                    "non_partants": (
                        base["non_partants"]
                    ),
                    "statut": statut,
                    "moteurs": lignes
                })

                rapport["moteurs"] = lignes
                rapport["course_id"] = cid
                rapport["status"] = statut

                # =================================
                # 5. PROCÈS-VERBAL DU FIGÉ
                # =================================

                if document:
                    chemin_pv = DATA / "pv" / (
                        identifiant(cid) + ".json"
                    )

                    if not chemin_pv.exists():
                        ecrire(
                            chemin_pv,
                            {
                                "course_id": cid,
                                "statut": "PV_FIGE",
                                "fige_a": (
                                    document["fige_a"]
                                ),
                                "sha256": (
                                    document["sha256"]
                                ),
                                "moteurs": lignes
                            }
                        )

        except (
            ValueError, KeyError,
            TypeError, OSError
        ) as erreur:
            rapport["status"] = (
                "🔴 ERREUR D'ANALYSE"
            )
            ajouter_erreur(
                rapport,
                erreur
            )

    else:
        ajouter_erreur(
            rapport,
            "data/course.json absent"
        )

    # =========================================
    # 6. AUDITS APRÈS COURSE
    # =========================================

    for path in fichiers("arrivees"):
        try:
            arrivee = lire(path)

            cid = identifiant(
                arrivee["course_id"]
            )

            chemin_fige = DATA / "figes" / (
                cid + ".json"
            )

            chemin_audit = DATA / "audits" / (
                cid + ".json"
            )

            if (
                chemin_fige.exists()
                and not chemin_audit.exists()
            ):
                document = lire(
                    chemin_fige
                )

                verifier_fige(document)

                resultat = auditer(
                    document,
                    arrivee
                )

                ecrire(
                    chemin_audit,
                    resultat
                )

        except (
            ValueError, KeyError,
            TypeError, OSError
        ) as erreur:
            ajouter_erreur(
                rapport,
                f"{path.name}: {erreur}"
            )

    # =========================================
    # 7. CHARGEMENT DES ARCHIVES
    # =========================================

    pv = charger_collection("pv")
    figes = charger_collection("figes")
    audits = charger_collection("audits")

    rapport["pv_count"] = len(pv)
    rapport["figes_count"] = len(figes)
    rapport["audits_count"] = len(audits)
    rapport["courses_count"] = len(courses)

    # =========================================
    # 8. PUBLICATION POUR LE SITE
    # =========================================

    ecrire(
        DATA / "courses.json",
        {"courses": courses}
    )

    ecrire(
        DATA / "pv.json",
        {"pv": pv}
    )

    ecrire(
        DATA / "figes.json",
        {"figes": figes}
    )

    ecrire(
        DATA / "audits.json",
        {"audits": audits}
    )

    ecrire(
        DATA / "rapport.json",
        rapport
    )

    ecrire(
        DATA / "latest.json",
        rapport
    )

    print(
        json.dumps(
            rapport,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    main()
            
