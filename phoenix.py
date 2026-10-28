#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""X1000 PHOENIX — Gestion sécurisée des FIGÉS historiques."""

import hashlib
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
FIGES = DATA / "figes"

MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def lire(chemin):
    """Lire un document JSON sans le modifier."""
    with open(chemin, "r", encoding="utf-8") as fichier:
        return json.load(fichier)


def ecrire(chemin, document):
    """Écrire un JSON, sans écraser un FIGÉ historique."""
    chemin = Path(chemin)

    if chemin.parent.resolve() == FIGES.resolve():
        if chemin.exists():
            raise FileExistsError(
                f"FIGÉ historique protégé : {chemin}"
            )

    chemin.parent.mkdir(parents=True, exist_ok=True)

    with open(chemin, "x" if chemin.parent.resolve() == FIGES.resolve() else "w",
              encoding="utf-8") as fichier:
        json.dump(
            document,
            fichier,
            ensure_ascii=False,
            indent=2
        )


def identifiant(course_id):
    """Produire un identifiant de fichier sécurisé."""
    valeur = str(course_id).strip()

    if not valeur:
        raise ValueError("Identifiant de course vide")

    return re.sub(r"[^a-zA-Z0-9_-]", "_", valeur)


def chemin_fige(course_id):
    """Construire le chemin d'un FIGÉ."""
    return FIGES / (identifiant(course_id) + ".json")


def rapport_fige(document):
    """Extraire l'analyse d'un FIGÉ historique."""
    if not isinstance(document, dict):
        raise ValueError("Document FIGÉ invalide")

    rapport = document.get("rapport")
    if isinstance(rapport, dict):
        return rapport

    contenu = document.get("contenu")
    if isinstance(contenu, dict):
        analyse = contenu.get("analyse")
        if isinstance(analyse, dict):
            return analyse

    raise ValueError("Format FIGÉ inconnu")


def verifier_fige(document):
    """Vérifier la structure sans modifier le FIGÉ."""
    rapport = rapport_fige(document)

    moteurs = rapport.get("moteurs")

    if not isinstance(moteurs, list):
        raise ValueError("Liste des moteurs invalide")

    for moteur in moteurs:
        if not isinstance(moteur, dict):
            raise ValueError("Moteur FIGÉ invalide")

        nom = moteur.get("moteur")
        if nom not in MOTEURS:
            raise ValueError(f"Moteur inconnu : {nom}")

    empreinte = document.get("sha256")

    if not isinstance(empreinte, str) or not re.fullmatch(
        r"[a-fA-F0-9]{64}", empreinte
    ):
        raise ValueError("Empreinte SHA256 absente ou invalide")

    return True


def statut_fige(document):
    """Classer un FIGÉ sans modifier son historique."""
    verifier_fige(document)

    rapport = rapport_fige(document)
    moteurs = rapport["moteurs"]

    officiels = [
        moteur
        for moteur in moteurs
        if moteur.get("validation") == "OFFICIEL_VALIDE"
        and moteur.get("pari_retenu") not in (None, "", [], {})
    ]

    if officiels:
        return "PARI_OFFICIEL_FIGE"

    return "FIGE_INDICATIF"


def bilan_fige(document):
    """Produire un bilan de classification indépendant."""
    verifier_fige(document)

    rapport = rapport_fige(document)

    return {
        "course_id": rapport.get("course_id"),
        "sha256": document["sha256"],
        "statut": statut_fige(document),
        "moteurs": rapport.get("moteurs", []),
        "historique_modifie": False
    }
