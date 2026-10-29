#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX
REPARATION QUALIFICATIONS ET AUDITS - V10

- Controle des courses françaises
- Qualification avant depart
- Diagnostic des exclusions
- Analyse M1-M5 sans consensus obligatoire
- Controle des FIGES SHA256
- Detection des arrivees disponibles
- Preservation des archives historiques
- Aucun resultat invente
- Aucun pronostic retroactif
"""

import json
import sys
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import (
    DATA,
    lire,
    ecrire,
    verifier_fige,
    controle_fige,
    rapport_fige,
)

from reparer_figes_audits import (
    charger_figes,
    charger_arrivees,
    charger_audits_existants,
    verifier_audits,
    publier as publier_figes_audits,
)

PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")

VERSION = "X1000-PHOENIX-10.0"


def maintenant():
    return dt.datetime.now(PARIS)


def date_valide(valeur):
    if not isinstance(valeur, str):
        return None
    try:
        date = dt.datetime.fromisoformat(
            valeur.replace("Z", "+00:00")
        )
        if date.tzinfo is None:
            return None
        return date.astimezone(PARIS)
    except (ValueError, TypeError, OverflowError):
        return None


def collection(nom, cle, erreurs):
    chemin = DATA / nom

    if not chemin.is_file():
        return []

    try:
        objet = lire(chemin)

        if isinstance(objet, list):
            return objet

        if isinstance(objet, dict):
            lignes = objet.get(cle, [])
            if isinstance(lignes, list):
                return lignes

        raise ValueError("Format de collection incorrect")

    except (OSError, ValueError, TypeError) as exc:
        erreurs.append(f"{nom}: {exc}")
        return []


def est_francaise(course):
    return (
        course.get("localisation_france_verifiee")
        is True
    )


def est_non_partant(cheval):
    statut = str(
        cheval.get("statut") or ""
    ).upper().replace("-", "_").replace(" ", "_")

    return (
        cheval.get("non_partant") is True
        or statut in (
            "NP", "NON_PARTANT",
            "NONPARTANT", "FORFAIT"
        )
    )


def selection_valide(moteur, actifs):
    if not isinstance(moteur, dict):
        return False

    if moteur.get("moteur") not in MOTEURS:
        return False

    ordre = moteur.get(
        "ordre_espere",
        moteur.get("ordre", [])
    )

    if not isinstance(ordre, list) or not ordre:
        return False

    try:
        numeros = [
            int(n) for n in ordre
            if not isinstance(n, bool)
        ]
    except (ValueError, TypeError):
        return False

    return (
        len(numeros) == len(ordre)
        and len(set(numeros)) == len(numeros)
        and all(n in actifs for n in numeros)
    )


def qualifier(course, instant):
    raisons = []

    if not est_francaise(course):
        raisons.append(
            "Localisation France non verifiee"
        )

    if course.get("depart_verifie") is not True:
        raisons.append(
            "Horaire de depart non verifie"
        )

    depart = date_valide(course.get("depart"))

    if depart is None:
        raisons.append("Depart invalide")
    elif instant >= depart:
        raisons.append("Course deja partie")

    collecte = date_valide(
        course.get("collecte_a")
    )

    if collecte is None:
        raisons.append(
            "Horodatage collecte absent"
        )
    else:
        age = (instant - collecte).total_seconds()

        if age < -60:
            raisons.append(
                "Collecte datee du futur"
            )
        elif age > 1200:
            raisons.append(
                "Collecte trop ancienne"
            )

    preuve = course.get("controle_source")

    if not isinstance(preuve, dict):
        raisons.append(
            "Preuve API absente"
        )
    elif (
        preuve.get("mode") != "API_REPONSE_DIRECTE"
        or preuve.get("structure_validee") is not True
        or preuve.get("participants_url")
           != course.get("source")
    ):
        raisons.append(
            "Preuve API incomplete"
        )

    partants = course.get("partants", [])

    if not isinstance(partants, list):
        partants = []

    actifs = set()
    numeros_vus = set()

    for cheval in partants:
        if not isinstance(cheval, dict):
            raisons.append("Fiche cheval invalide")
            continue

        try:
            numero = int(cheval["numero"])
            if numero <= 0:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raisons.append("Numero cheval invalide")
            continue

        if numero in numeros_vus:
            raisons.append("Numero cheval duplique")

        numeros_vus.add(numero)

        if not est_non_partant(cheval):
            actifs.add(numero)

    if len(actifs) < 2:
        raisons.append(
            "Nombre de partants insuffisant"
        )

    moteurs = course.get("moteurs", [])

    if not isinstance(moteurs, list):
        moteurs = []

    valides = sorted({
        m["moteur"]
        for m in moteurs
        if selection_valide(m, actifs)
    })

    if not valides:
        raisons.append(
            "Aucune selection M1-M5 exploitable"
        )

    return {
        "qualifiee": not raisons,
        "raisons": list(dict.fromkeys(raisons)),
        "moteurs_valides": valides,
        "partants_actifs": len(actifs),
    }


def traiter_qualifications(erreurs):
    courses = collection(
        "publication_courses.json",
        "courses",
        erreurs
    )

    # Si la publication n'existe pas encore,
    # consulter la collecte brute.
    if not courses:
        courses = collection(
            "collecte.json",
            "courses",
            erreurs
        )

    instant = maintenant()
    resultats = []
    qualifies = 0

    for course in courses:
        if not isinstance(course, dict):
            continue

        cid = course.get(
            "id", course.get("course_id")
        )

        if not cid:
            continue

        controle = qualifier(course, instant)

        if controle["qualifiee"]:
            qualifies += 1

        resultats.append({
            "course_id": str(cid),
            "hippodrome": course.get("hippodrome"),
            "depart": course.get("depart"),
            "qualifiee": controle["qualifiee"],
            "qualification": (
                "QUALIFIEE_AVANT_DEPART"
                if controle["qualifiee"]
                else "NON_QUALIFIEE"
            ),
            "moteurs_valides":
                controle["moteurs_valides"],
            "partants_actifs":
                controle["partants_actifs"],
            "raisons":
                controle["raisons"],
            "verifie_a": instant.isoformat(),
        })

    rapport = {
        "version": VERSION,
        "genere_a_paris": instant.isoformat(),
        "courses_examinees": len(resultats),
        "courses_qualifiees": qualifies,
        "courses_non_qualifiees":
            len(resultats) - qualifies,
        "qualifications": resultats,
        "erreurs": erreurs[:],
    }

    ecrire(
        DATA / "publication_qualifications.json",
        rapport
    )

    return rapport


def traiter_audits(erreurs):
    figes = charger_figes(erreurs)
    arrivees = charger_arrivees(erreurs)

    historiques = charger_audits_existants(
        figes, erreurs
    )

    audits = verifier_audits(
        historiques, figes, erreurs
    )

    # Aucune arrivée n'est certifiée par
    # la simple présence d'une URL HTTPS.
    # Les audits historiques validés sont
    # conservés; les autres restent candidats.

    index_audits = {
        a.get("fige_sha256", "").lower()
        for a in audits
        if isinstance(a.get("fige_sha256"), str)
    }

    candidats = []
    attentes = []

    for document in figes:
        try:
            verifier_fige(document)
            controle = controle_fige(document)

            if controle.get("integrite") != "VERIFIE":
                continue

            analyse = rapport_fige(document)
            cid = str(analyse["course_id"])
            sha = document["sha256"].lower()

            if sha in index_audits:
                continue

            if cid not in arrivees:
                attentes.append(cid)
                continue

            candidats.append({
                "course_id": cid,
                "fige_sha256": sha,
                "statut":
                    "ARRIVEE_A_VERIFIER",
                "source_candidate":
                    arrivees[cid]["source"],
                "arrivee_candidate":
                    arrivees[cid]["arrivee"],
                "message":
                    "Verification independante "
                    "de la source necessaire",
            })

        except (
            ValueError, KeyError,
            TypeError, AttributeError
        ) as exc:
            erreurs.append(
                "Controle FIGE: " + str(exc)
            )

    rapport = {
        "version": VERSION,
        "genere_a_paris":
            maintenant().isoformat(),
        "figes_verifies": len(figes),
        "audits_historiques_valides":
            len(audits),
        "audits_nouveaux_certifies": 0,
        "candidats_a_verifier": candidats,
        "en_attente_arrivee":
            sorted(set(attentes)),
        "note":
            "Aucun audit nouveau certifie "
            "sans verification de la source.",
        "erreurs": erreurs[:],
    }

    ecrire(
        DATA / "publication_diagnostic_audits.json",
        rapport
    )

    return rapport


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    erreurs = []

    print("X1000 PHOENIX - REPARATION V10")

    qualifications = traiter_qualifications(
        erreurs
    )

    print(
        "Courses examinees:",
        qualifications["courses_examinees"]
    )
    print(
        "Courses qualifiees:",
        qualifications["courses_qualifiees"]
    )

    # Utiliser le module historique existant.
    # Il conserve les FIGES et les audits
    # dans leurs publications derivees.
    publier_figes_audits()

    audits = traiter_audits(erreurs)

    print(
        "FIGES verifies:",
        audits["figes_verifies"]
    )
    print(
        "Audits historiques valides:",
        audits["audits_historiques_valides"]
    )
    print(
        "Candidats a verifier:",
        len(audits["candidats_a_verifier"])
    )
    print(
        "Erreurs diagnostiquees:",
        len(erreurs)
    )

    print(
        json.dumps({
            "statut": "CONTROLE_TERMINE",
            "qualifications":
                qualifications["courses_qualifiees"],
            "audits":
                audits["audits_historiques_valides"],
            "erreurs": erreurs[:30],
        }, ensure_ascii=False, indent=2)
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
