
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🇸🇳🧠🔥 X1000 PHOENIX
Gestion sécurisée des analyses, PV et FIGÉS M1–M5.

- Aucune prédiction fictive
- Aucun FIGÉ vide créé
- Aucun FIGÉ historique écrasé
- Compatibilité avec publication.py
"""

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
FIGES = DATA / "figes"

PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def maintenant():
    """Heure actuelle de Paris."""
    return dt.datetime.now(PARIS).isoformat()


def lire(chemin):
    """Lire un fichier JSON."""
    with open(chemin, "r", encoding="utf-8") as fichier:
        return json.load(fichier)


def ecrire(chemin, document):
    """Écrire un JSON sans écraser les FIGÉS historiques."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)

    protege = chemin.parent.resolve() == FIGES.resolve()

    mode = "x" if protege else "w"

    with open(chemin, mode, encoding="utf-8") as fichier:
        json.dump(
            document,
            fichier,
            ensure_ascii=False,
            indent=2
        )


def identifiant(course_id):
    """Créer un identifiant de fichier sécurisé."""
    valeur = str(course_id).strip()

    if not valeur:
        raise ValueError("Identifiant de course vide")

    return re.sub(r"[^a-zA-Z0-9_-]", "_", valeur)


def chemin_fige(course_id):
    """Chemin du FIGÉ historique d'une course."""
    return FIGES / (identifiant(course_id) + ".json")


def rapport_fige(document):
    """Extraire le rapport historique."""
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


def empreinte_rapport(rapport):
    """Calculer une empreinte canonique d'un rapport."""
    contenu = json.dumps(
        rapport,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":")
    ).encode("utf-8")

    return hashlib.sha256(contenu).hexdigest()


def verifier_fige(document):
    """Vérifier la structure d'un FIGÉ sans le modifier."""
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

    if not isinstance(empreinte, str):
        raise ValueError("Empreinte SHA256 absente")

    if not re.fullmatch(r"[a-fA-F0-9]{64}", empreinte):
        raise ValueError("Empreinte SHA256 invalide")

    # Les anciens FIGÉS peuvent utiliser un autre schéma
    # d'empreinte. Ne pas les réécrire ni présumer
    # qu'une empreinte bien formée prouve leur intégrité.
    return True


def statut_fige(document):
    """Classifier un FIGÉ historique."""
    verifier_fige(document)

    rapport = rapport_fige(document)

    officiels = [
        moteur
        for moteur in rapport["moteurs"]
        if moteur.get("validation") == "OFFICIEL_VALIDE"
        and moteur.get("pari_retenu") not in (
            None, "", [], {}
        )
    ]

    if officiels:
        return "PARI_OFFICIEL_FIGE"

    return "FIGE_INDICATIF"


def bilan_fige(document):
    """Construire un bilan sans modifier l'historique."""
    verifier_fige(document)

    rapport = rapport_fige(document)

    return {
        "course_id": rapport.get("course_id"),
        "sha256": document["sha256"],
        "statut": statut_fige(document),
        "moteurs": rapport["moteurs"],
        "historique_modifie": False
    }


def analyser(course):
    """
    Analyse de sécurité.

    En l'absence de moteurs prédictifs réellement
    raccordés, aucune sélection n'est inventée.
    """
    if not isinstance(course, dict):
        raise ValueError("Course invalide")

    cid = course.get("id")

    if not cid:
        raise ValueError("Identifiant de course absent")

    return {
        "course_id": cid,
        "hippodrome": course.get("hippodrome"),
        "depart": course.get("depart"),
        "source": course.get("source"),
        "nombre_partants": course.get("nombre_partants"),
        "analyse_a": maintenant(),
        "moteurs": [],
        "validation": "EN_ATTENTE_MOTEURS",
    }


def figer(analyse):
    """
    Récupérer un FIGÉ existant si disponible.

    Ne jamais fabriquer de FIGÉ sans moteurs validés.
    """
    if not isinstance(analyse, dict):
        raise ValueError("Analyse invalide")

    cid = analyse.get("course_id")

    if not cid:
        raise ValueError("Course sans identifiant")

    chemin = chemin_fige(cid)

    if chemin.exists():
        document = lire(chemin)
        verifier_fige(document)

        rapport = rapport_fige(document)

        if str(rapport.get("course_id")) != str(cid):
            raise ValueError(
                "FIGÉ historique associé à une autre course"
            )

        return document

    # Aucun nouveau FIGÉ fictif.
    return None


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    FIGES.mkdir(parents=True, exist_ok=True)

    print("X1000 PHOENIX — module chargé")
    print("Heure Paris :", maintenant())
    print("Moteurs :", ", ".join(MOTEURS))
    print("Protection FIGÉS : ACTIVE")
    print("Analyse réelle : EN ATTENTE")
