#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🇸🇳🧠🔥 X1000 PHOENIX
INTELLIGENCE HIPPIQUE VIVANTE — M1 À M5

Gestion sécurisée :
- Analyses des courses
- Moteurs M1, M2, M3, M4 et M5
- PV et FIGÉS historiques
- Vérification SHA256
- Protection contre les écrasements
- Compatibilité avec publication.py

Règles :
- Aucune donnée hippique inventée
- Aucun pronostic fictif
- Aucun FIGÉ vide créé
- Aucun FIGÉ historique modifié
- Aucun résultat officiel inventé
"""

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import tempfile

from pathlib import Path
from zoneinfo import ZoneInfo


# ==================================================
# CONFIGURATION
# ==================================================

BASE = Path(__file__).resolve().parent

DATA = BASE / "data"
FIGES = DATA / "figes"

PARIS = ZoneInfo("Europe/Paris")

MOTEURS = (
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
)


# ==================================================
# HORLOGE
# ==================================================

def maintenant():
    """Retourner l'heure actuelle de Paris."""
    return dt.datetime.now(PARIS).isoformat()


def date_paris():
    """Retourner la date actuelle de Paris."""
    return dt.datetime.now(PARIS).date().isoformat()


# ==================================================
# IDENTIFIANTS
# ==================================================

def identifiant(course_id):
    """Créer un identifiant de fichier sécurisé."""

    if course_id is None or isinstance(course_id, bool):
        raise ValueError("Identifiant de course invalide")

    valeur = str(course_id).strip()

    if not valeur:
        raise ValueError("Identifiant de course vide")

    resultat = re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        valeur
    )

    if not resultat or not re.search(
        r"[a-zA-Z0-9]",
        resultat
    ):
        raise ValueError(
            "Identifiant de course non exploitable"
        )

    return resultat


def chemin_fige(course_id):
    """Retourner le chemin historique d'un FIGÉ."""

    return FIGES / (
        identifiant(course_id) + ".json"
    )


# ==================================================
# LECTURE JSON
# ==================================================

def _sans_doublons(paires):
    """Refuser les clés JSON dupliquées."""

    resultat = {}

    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError(
                f"Clé JSON dupliquée : {cle}"
            )

        resultat[cle] = valeur

    return resultat


def lire(chemin):
    """Lire un JSON sans modifier son contenu."""

    chemin = Path(chemin)

    with chemin.open(
        "r",
        encoding="utf-8"
    ) as fichier:

        return json.load(
            fichier,
            object_pairs_hook=_sans_doublons
        )


# ==================================================
# ÉCRITURE JSON SÉCURISÉE
# ==================================================

def _est_fige(chemin):
    """
    Déterminer si un chemin appartient
    au répertoire historique FIGES.
    """

    chemin = Path(chemin).resolve()
    dossier = FIGES.resolve()

    return (
        chemin == dossier
        or dossier in chemin.parents
    )


def ecrire(chemin, document):
    """
    Écrire un JSON.

    FIGÉS :
        création exclusive, sans écrasement.

    Autres fichiers :
        écriture temporaire puis remplacement.
    """

    chemin = Path(chemin)

    chemin.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    contenu = json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        allow_nan=False
    ) + "\n"

    if _est_fige(chemin):

        if not isinstance(document, dict):
            raise ValueError(
                "Un FIGÉ doit être un document JSON"
            )

        verifier_fige(
            document,
            exiger_integrite=True
        )

        with chemin.open(
            "x",
            encoding="utf-8"
        ) as fichier:

            fichier.write(contenu)

        return chemin

    temporaire = None

    try:

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(chemin.parent),
            prefix=".x1000_",
            suffix=".tmp",
            delete=False
        ) as fichier:

            temporaire = Path(fichier.name)

            fichier.write(contenu)
            fichier.flush()
            os.fsync(fichier.fileno())

        os.replace(
            temporaire,
            chemin
        )

        return chemin

    finally:

        if (
            temporaire is not None
            and temporaire.exists()
        ):
            temporaire.unlink()


# ==================================================
# EXTRACTION DES FIGÉS
# ==================================================

def rapport_fige(document):
    """
    Extraire le rapport d'un FIGÉ.

    Formats acceptés :
    1. document["rapport"]
    2. document["contenu"]["analyse"]
    """

    if not isinstance(document, dict):
        raise ValueError(
            "Document FIGÉ invalide"
        )

    rapport = document.get("rapport")

    if isinstance(rapport, dict):
        return rapport

    contenu = document.get("contenu")

    if isinstance(contenu, dict):

        analyse = contenu.get("analyse")

        if isinstance(analyse, dict):
            return analyse

    raise ValueError(
        "Format FIGÉ inconnu"
    )


# ==================================================
# EMPREINTE SHA256
# ==================================================

def empreinte_rapport(rapport):
    """
    Calculer l'empreinte SHA256 canonique
    d'un rapport.

    Une empreinte détecte une modification,
    mais ne prouve pas à elle seule l'origine
    ni l'heure historique du document.
    """

    if not isinstance(rapport, dict):
        raise ValueError(
            "Rapport invalide"
        )

    contenu = json.dumps(
        rapport,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False
    ).encode("utf-8")

    return hashlib.sha256(
        contenu
    ).hexdigest()


# ==================================================
# VÉRIFICATION DES FIGÉS
# ==================================================

def controle_fige(document):
    """
    Examiner un FIGÉ sans le modifier.

    États :
    - VERIFIE
    - NON_VERIFIABLE
    - INVALIDE

    Les anciens formats d'empreinte ne sont
    jamais considérés comme vérifiés
    par simple présence de 64 caractères.
    """

    resultat = {
        "integrite": "INVALIDE",
        "course_id": None,
        "moteurs": [],
        "empreinte_presente": False,
        "empreinte_concordante": False,
        "message": "",
    }

    try:

        rapport = rapport_fige(document)

        cid = rapport.get("course_id")

        if cid is None or str(cid).strip() == "":
            raise ValueError(
                "Identifiant de course absent"
            )

        resultat["course_id"] = str(cid)

        moteurs = rapport.get("moteurs")

        if not isinstance(moteurs, list):
            raise ValueError(
                "Liste des moteurs invalide"
            )

        noms = set()

        for moteur in moteurs:

            if not isinstance(moteur, dict):
                raise ValueError(
                    "Structure moteur invalide"
                )

            nom = moteur.get("moteur")

            if nom not in MOTEURS:
                raise ValueError(
                    f"Moteur inconnu : {nom}"
                )

            if nom in noms:
                raise ValueError(
                    f"Moteur dupliqué : {nom}"
                )

            noms.add(nom)

        resultat["moteurs"] = sorted(noms)

        empreinte = document.get("sha256")

        if not isinstance(empreinte, str):
            raise ValueError(
                "Empreinte SHA256 absente"
            )

        if not re.fullmatch(
            r"[a-fA-F0-9]{64}",
            empreinte
        ):
            raise ValueError(
                "Format SHA256 invalide"
            )

        resultat["empreinte_presente"] = True

        calculee = empreinte_rapport(
            rapport
        )

        concordance = hmac.compare_digest(
            calculee.lower(),
            empreinte.lower()
        )

        resultat[
            "empreinte_concordante"
        ] = concordance

        if concordance:

            resultat["integrite"] = "VERIFIE"

            resultat["message"] = (
                "Empreinte SHA256 canonique "
                "concordante"
            )

        else:

            resultat["integrite"] = (
                "NON_VERIFIABLE"
            )

            resultat["message"] = (
                "Empreinte non concordante. "
                "Ancien schéma possible ou "
                "document modifié. "
                "Contrôle historique nécessaire."
            )

    except (
        ValueError,
        TypeError,
        OverflowError
    ) as erreur:

        resultat["integrite"] = "INVALIDE"
        resultat["message"] = str(erreur)

    return resultat


def verifier_fige(
    document,
    exiger_integrite=False
):
    """
    Vérifier un FIGÉ sans le modifier.

    Compatibilité historique :
    les anciens documents structurellement
    valides peuvent rester consultables.

    Pour créer un nouveau FIGÉ :
    exiger_integrite=True.
    """

    controle = controle_fige(document)

    if controle["integrite"] == "INVALIDE":

        raise ValueError(
            controle["message"]
        )

    if (
        exiger_integrite
        and controle["integrite"] != "VERIFIE"
    ):

        raise ValueError(
            "Intégrité du FIGÉ non confirmée : "
            + controle["message"]
        )

    return True


# ==================================================
# STATUT DES FIGÉS
# ==================================================

def statut_fige(document):
    """
    Déterminer si un FIGÉ contient
    au moins un pari officiellement validé.

    Le statut du pari ne constitue pas
    une preuve d'intégrité cryptographique.
    """

    verifier_fige(document)

    rapport = rapport_fige(document)

    moteurs = rapport.get(
        "moteurs",
        []
    )

    officiels = []

    for moteur in moteurs:

        if not isinstance(moteur, dict):
            continue

        validation = moteur.get(
            "validation"
        )

        pari = moteur.get(
            "pari_retenu"
        )

        if (
            validation == "OFFICIEL_VALIDE"
            and pari not in (
                None,
                "",
                [],
                {}
            )
        ):

            officiels.append(
                moteur
            )

    if officiels:
        return "PARI_OFFICIEL_FIGE"

    return "FIGE_INDICATIF"


# ==================================================
# BILAN HISTORIQUE
# ==================================================

def bilan_fige(document):
    """
    Construire un bilan de FIGÉ
    sans modifier son contenu.
    """

    verifier_fige(document)

    rapport = rapport_fige(document)
    controle = controle_fige(document)

    return {
        "course_id": rapport.get(
            "course_id"
        ),
        "sha256": document.get(
            "sha256"
        ),
        "integrite": controle[
            "integrite"
        ],
        "message_integrite": controle[
            "message"
        ],
        "statut": statut_fige(
            document
        ),
        "moteurs": rapport.get(
            "moteurs",
            []
        ),
        "historique_modifie": False,
    }


# ==================================================
# DIAGNOSTIC DES MOTEURS
# ==================================================

def diagnostic_moteurs():
    """
    État réel des moteurs prédictifs.

    Aucun moteur ne doit être déclaré
    opérationnel sans implémentation réelle.
    """

    return {
        "M1": "NON_RACCORDE",
        "M2": "NON_RACCORDE",
        "M3": "NON_RACCORDE",
        "M4": "NON_RACCORDE",
        "M5": "NON_RACCORDE",
        "analyse_reelle": False,
        "nouveaux_figes": False,
        "heure_paris": maintenant(),
    }


# ==================================================
# ANALYSE DES COURSES
# ==================================================

def analyser(course):
    """
    Préparer une analyse de course.

    Les cinq moteurs prédictifs réels
    ne sont pas encore raccordés.

    Ne jamais fabriquer de pronostic
    pour remplir artificiellement
    le tableau officiel.
    """

    if not isinstance(course, dict):
        raise ValueError(
            "Course invalide"
        )

    cid = course.get(
        "id",
        course.get("course_id")
    )

    if cid is None or str(cid).strip() == "":
        raise ValueError(
            "Identifiant de course absent"
        )

    return {
        "course_id": cid,
        "hippodrome": course.get(
            "hippodrome"
        ),
        "depart": course.get(
            "depart"
        ),
        "source": course.get(
            "source"
        ),
        "nombre_partants": course.get(
            "nombre_partants"
        ),
        "analyse_a": maintenant(),
        "moteurs": [],
        "validation": "EN_ATTENTE_MOTEURS",
        "qualification": "NON_EVALUEE",
        "pari_officiel": False,
    }


# ==================================================
# GESTION DES FIGÉS
# ==================================================

def figer(analyse):
    """
    Récupérer un FIGÉ historique existant.

    Aucun nouveau FIGÉ n'est créé
    sans moteurs prédictifs réellement
    raccordés et validés.

    Les FIGÉS historiques restent intacts.
    """

    if not isinstance(analyse, dict):
        raise ValueError(
            "Analyse invalide"
        )

    cid = analyse.get(
        "course_id"
    )

    if cid is None or str(cid).strip() == "":
        raise ValueError(
            "Course sans identifiant"
        )

    chemin = chemin_fige(
        cid
    )

    if chemin.exists():

        document = lire(
            chemin
        )

        verifier_fige(
            document
        )

        rapport = rapport_fige(
            document
        )

        if str(
            rapport.get("course_id")
        ) != str(cid):

            raise ValueError(
                "FIGÉ historique associé "
                "à une autre course"
            )

        return document

    # Aucun FIGÉ fictif.
    return None


# ==================================================
# CONTRÔLE DU DOSSIER HISTORIQUE
# ==================================================

def auditer_figes_historiques():
    """
    Examiner les FIGÉS existants.

    Ne jamais modifier ou supprimer
    un document historique.
    """

    resultat = {
        "verifies": 0,
        "non_verifiables": 0,
        "invalides": 0,
        "documents": [],
        "heure_paris": maintenant(),
    }

    if not FIGES.exists():
        return resultat

    for chemin in sorted(
        FIGES.glob("*.json")
    ):

        try:

            document = lire(
                chemin
            )

            controle = controle_fige(
                document
            )

        except Exception as erreur:

            controle = {
                "integrite": "INVALIDE",
                "message": str(erreur),
                "course_id": None,
            }

        etat = controle["integrite"]

        if etat == "VERIFIE":
            resultat["verifies"] += 1

        elif etat == "NON_VERIFIABLE":
            resultat["non_verifiables"] += 1

        else:
            resultat["invalides"] += 1

        resultat["documents"].append({
            "fichier": chemin.name,
            "course_id": controle.get(
                "course_id"
            ),
            "integrite": etat,
            "message": controle.get(
                "message"
            ),
        })

    return resultat


# ==================================================
# EXÉCUTION DIRECTE
# ==================================================

def main():

    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    FIGES.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        "🇸🇳🧠🔥 X1000 PHOENIX"
    )

    print(
        "Heure Paris :",
        maintenant()
    )

    print(
        "Moteurs :",
        ", ".join(MOTEURS)
    )

    print(
        "Protection FIGÉS : ACTIVE"
    )

    print(
        "Analyse prédictive : EN ATTENTE"
    )

    historique = auditer_figes_historiques()

    print(
        "FIGÉS vérifiés :",
        historique["verifies"]
    )

    print(
        "FIGÉS non vérifiables :",
        historique["non_verifiables"]
    )

    print(
        "FIGÉS invalides :",
        historique["invalides"]
    )

    print(
        "Diagnostic :",
        json.dumps(
            diagnostic_moteurs(),
            ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
