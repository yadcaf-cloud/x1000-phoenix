#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — réparation FIGÉS et audits M1-M5.

Exécuter après publication.py.
Ne crée aucun pronostic rétroactif.
Ne modifie jamais un FIGÉ historique.
"""

import json
import sys
from pathlib import Path

from phoenix import (
    DATA, FIGES, AUDITS,
    lire, ecrire, auditer, verifier_fige,
    verifier_source, identifiant,
    maintenant, date_paris
)

MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def charger_collection(nom, cle):
    chemin = DATA / nom
    if not chemin.exists():
        return []

    objet = lire(chemin)

    if isinstance(objet, list):
        return objet

    if isinstance(objet, dict):
        valeur = objet.get(cle, [])
        if isinstance(valeur, list):
            return valeur

    raise ValueError("Format invalide : " + nom)


def charger_documents(dossier):
    documents = []
    erreurs = []

    for chemin in sorted(dossier.glob("*.json")):
        try:
            document = lire(chemin)
            if not isinstance(document, dict):
                raise ValueError("Document non objet")
            documents.append(document)
        except (ValueError, TypeError, OSError) as exc:
            erreurs.append(f"{chemin}: {exc}")

    return documents, erreurs


def charger_figes():
    documents, erreurs = charger_documents(FIGES)

    try:
        documents += charger_collection(
            "figes.json", "figes"
        )
    except (ValueError, OSError) as exc:
        erreurs.append(str(exc))

    valides = []
    empreintes = set()

    for document in documents:
        try:
            verifier_fige(document)
            sha = document["sha256"]

            if sha not in empreintes:
                empreintes.add(sha)
                valides.append(document)

        except (ValueError, TypeError, KeyError) as exc:
            erreurs.append("FIGÉ rejeté : " + str(exc))

    return valides, erreurs


def rapport_du_fige(fige):
    if "rapport" in fige:
        return fige["rapport"]

    return fige["contenu"]["analyse"]


def charger_arrivees():
    """Arrivées fournies par un fichier de source vérifiée."""
    chemins = [
        DATA / "arrivees_officielles.json",
        DATA / "publication_arrivees.json"
    ]

    arrivees = {}
    erreurs = []

    for chemin in chemins:
        if not chemin.exists():
            continue

        try:
            objet = lire(chemin)

            if isinstance(objet, dict):
                lignes = objet.get(
                    "courses",
                    objet.get("arrivees", [])
                )
            elif isinstance(objet, list):
                lignes = objet
            else:
                raise ValueError("Format incorrect")

            if not isinstance(lignes, list):
                raise ValueError("Liste incorrecte")

            for ligne in lignes:
                if not isinstance(ligne, dict):
                    continue

                cid = ligne.get(
                    "course_id", ligne.get("id")
                )

                if not cid:
                    continue

                if ligne.get("statut") != "definitive":
                    continue

                if not verifier_source(ligne.get("source")):
                    erreurs.append(
                        f"{cid}: source non vérifiable"
                    )
                    continue

                ordre = ligne.get("arrivee")

                if (
                    not isinstance(ordre, list)
                    or len(ordre) < 5
                    or any(
                        type(n) is not int or n <= 0
                        for n in ordre
                    )
                    or len(set(ordre)) != len(ordre)
                ):
                    erreurs.append(
                        f"{cid}: arrivée invalide"
                    )
                    continue

                arrivees[cid] = {
                    "course_id": cid,
                    "statut": "definitive",
                    "source": ligne["source"],
                    "arrivee": ordre
                }

        except (OSError, ValueError, TypeError) as exc:
            erreurs.append(f"{chemin}: {exc}")

    return arrivees, erreurs


def auditer_figes(figes, arrivees):
    AUDITS.mkdir(parents=True, exist_ok=True)

    audits = []
    erreurs = []
    attentes = []

    for fige in figes:
        try:
            rapport = rapport_du_fige(fige)
            cid = rapport["course_id"]

            if cid not in arrivees:
                attentes.append(cid)
                continue

            arrivee = arrivees[cid]

            # La fonction officielle vérifie la cohérence
            # du FIGÉ et de l'arrivée.
            audit = auditer(fige, arrivee)

            audit["moteurs_attendus"] = list(MOTEURS)
            audit["controle"] = "FIGE_VERIFIE"
            audit["type"] = "AUDIT_APRES_COURSE"

            nom = (
                identifiant(cid)
                + "_"
                + fige["sha256"][:12]
                + ".json"
            )

            chemin = AUDITS / nom

            if chemin.exists():
                ancien = lire(chemin)
                if ancien.get("fige_sha256") != fige["sha256"]:
                    raise ValueError(
                        "Conflit avec audit historique"
                    )
                audit = ancien
            else:
                ecrire(chemin, audit)

            audits.append(audit)

        except (
            ValueError, KeyError, TypeError, OSError
        ) as exc:
            erreurs.append(str(exc))

    return audits, erreurs, attentes


def publier():
    DATA.mkdir(parents=True, exist_ok=True)

    figes, erreurs_figes = charger_figes()
    arrivees, erreurs_arrivees = charger_arrivees()

    audits, erreurs_audits, attentes = auditer_figes(
        figes, arrivees
    )

    # Les collections sont reconstruites uniquement
    # à partir des documents vérifiés.
    ecrire(
        DATA / "publication_figes.json",
        {"figes": figes}
    )

    ecrire(
        DATA / "publication_audits.json",
        {"audits": audits}
    )

    erreurs = (
        erreurs_figes
        + erreurs_arrivees
        + erreurs_audits
    )

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "module": "FIGES_AUDITS_M1_M5",
        "genere_a_paris": maintenant().isoformat(),
        "moteurs": list(MOTEURS),
        "figes_valides": len(figes),
        "audits_valides": len(audits),
        "arrivees_disponibles": len(arrivees),
        "en_attente_arrivee": sorted(set(attentes)),
        "erreurs": erreurs,
        "statut": (
            "ERREURS_A_VERIFIER" if erreurs
            else "AUDITS_DISPONIBLES" if audits
            else "FIGES_DISPONIBLES" if figes
            else "AUCUN_FIGE_VERIFIE"
        ),
        "note": (
            "Aucun FIGÉ rétroactif. "
            "Aucune arrivée inventée. "
            "Les sources doivent être vérifiées."
        )
    }

    ecrire(
        DATA / "publication_controle_figes_audits.json",
        rapport
    )

    print(json.dumps(
        rapport,
        ensure_ascii=False,
        indent=2
    ))

    return rapport


if __name__ == "__main__":
    try:
        publier()
    except Exception as exc:
        print(
            "ERREUR FIGÉS/AUDITS : " + str(exc),
            file=sys.stderr
        )
        sys.exit(1)
