#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - M1 a M5.
Analyses tracees, FIGES immuables et audits.
Aucune donnee PMU n'est inventee.
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
DATA = Path("data")
BASE = DATA
FIGES = DATA / "figes"
AUDITS = DATA / "audits"
MARGE_MINUTES = 20

CRITERES = (
    "forme", "aptitude", "regularite",
    "entourage", "valeur"
)

MOTEURS = {
    "M1": dict(zip(CRITERES, (4, 3, 2, 1, 2))),
    "M2": dict(zip(CRITERES, (2, 4, 3, 1, 2))),
    "M3": dict(zip(CRITERES, (2, 2, 2, 2, 4))),
    "M4": dict(zip(CRITERES, (3, 2, 3, 3, 1))),
    "M5": dict(zip(CRITERES, (2, 3, 2, 2, 3)))
}

def maintenant():
    return dt.datetime.now(PARIS)

def date_paris(valeur):
    date = dt.datetime.fromisoformat(str(valeur))
    if date.tzinfo is None:
        raise ValueError("Date sans fuseau horaire")
    return date.astimezone(PARIS)

def identifiant(valeur):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(valeur))

def lire(chemin):
    def uniques(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("Cle JSON dupliquee: " + cle)
            resultat[cle] = valeur
        return resultat

    with Path(chemin).open(encoding="utf-8") as f:
        return json.load(
            f,
            object_pairs_hook=uniques,
            parse_constant=lambda x: (_ for _ in ()).throw(
                ValueError("Nombre JSON invalide: " + x)
            )
        )

def ecrire(chemin, objet):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    temporaire.write_text(
        json.dumps(
            objet, ensure_ascii=False,
            indent=2, allow_nan=False
        ) + "\n",
        encoding="utf-8"
    )
    os.replace(temporaire, chemin)

def empreinte(objet):
    contenu = json.dumps(
        objet, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
        allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(contenu).hexdigest()

def verifier_source(source):
    return (
        isinstance(source, str)
        and source.startswith(("https://", "http://"))
        and len(source) > 12
    )

def valider_course(course):
    if not isinstance(course, dict):
        raise ValueError("Course invalide")

    for cle in ("id", "hippodrome", "depart", "partants"):
        if not course.get(cle):
            raise ValueError("Champ absent: " + cle)

    if not verifier_source(course.get("source")):
        raise ValueError("URL de provenance absente")

    depart = date_paris(course["depart"])
    chevaux = course["partants"]

    if not isinstance(chevaux, list):
        raise ValueError("Liste de partants invalide")

    actifs = []
    numeros = set()

    for cheval in chevaux:
        if not isinstance(cheval, dict):
            raise ValueError("Cheval invalide")

        numero = cheval.get("numero")
        if type(numero) is not int or numero <= 0:
            raise ValueError("Numero invalide")

        if numero in numeros:
            raise ValueError("Numero en double")
        numeros.add(numero)

        if cheval.get("non_partant") is True:
            continue

        notes = cheval.get("notes")
        if not isinstance(notes, dict):
            raise ValueError(
                "Notes absentes pour le cheval " + str(numero)
            )

        for critere in CRITERES:
            note = notes.get(critere)
            if (
                type(note) not in (int, float)
                or not math.isfinite(note)
                or not 0 <= note <= 10
            ):
                raise ValueError(
                    "Note non valide: " + str(numero)
                    + " / " + critere
                )

        actifs.append(cheval)

    if len(actifs) < 5:
        raise ValueError("Moins de cinq partants etudies")

    return depart, actifs

def analyser(course):
    depart, chevaux = valider_course(course)
    instant = maintenant()
    sorties = []

    for nom, poids in MOTEURS.items():
        classement = []

        for cheval in chevaux:
            notes = cheval["notes"]
            score = sum(
                notes[c] * poids[c] for c in CRITERES
            ) / sum(poids.values())

            classement.append({
                "numero": cheval["numero"],
                "score": round(score, 4)
            })

        classement.sort(
            key=lambda x: (-x["score"], x["numero"])
        )

        ordre = [x["numero"] for x in classement]
        ecart = classement[0]["score"] - classement[1]["score"]

        qualification = (
            "VERT" if ecart >= 0.5 else "JAUNE"
        )

        sorties.append({
            "moteur": nom,
            "gagnant_espere": ordre[0],
            "meilleur_place": ordre[1],
            "ordre_espere": ordre[:5],
            "pari_retenu": None,
            "qualification": qualification,
            "validation": "INDICATIF",
            "ecart_scores": round(ecart, 4),
            "scores": classement,
            "heure_paris": instant.isoformat()
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": course["id"],
        "hippodrome": course["hippodrome"],
        "depart": depart.isoformat(),
        "source": course["source"],
        "analyse_a": instant.isoformat(),
        "nombre_partants": len(chevaux),
        "moteurs": sorties,
        "statut": "ANALYSE_INDICATIVE",
        "avertissement": (
            "Scores heuristiques, sans probabilite "
            "calibree ni garantie de resultat."
        )
    }

def verifier_fige(document):
    if not isinstance(document, dict):
        raise ValueError("FIGE invalide")

    signature = document.get("sha256")
    contenu = {
        k: v for k, v in document.items()
        if k != "sha256"
    }

    if empreinte(contenu) != signature:
        raise ValueError("Empreinte FIGE incorrecte")

    if document.get("statut") != "FIGE_AVANT_DEPART":
        raise ValueError("Statut FIGE incorrect")

    rapport = document["rapport"]
    depart = date_paris(rapport["depart"])
    instant = date_paris(document["fige_a"])

    if instant >= depart:
        raise ValueError("FIGE apres depart")

    if not verifier_source(rapport.get("source")):
        raise ValueError("Source FIGE absente")

    noms = [m["moteur"] for m in rapport["moteurs"]]
    if sorted(noms) != sorted(MOTEURS):
        raise ValueError("Cinq moteurs requis")

    for m in rapport["moteurs"]:
        ordre = m["ordre_espere"]
        if (
            len(ordre) != 5
            or len(set(ordre)) != 5
            or m["gagnant_espere"] != ordre[0]
            or m["meilleur_place"] != ordre[1]
        ):
            raise ValueError("Selection incoherente")

    return True

def chemin_fige(course_id):
    return FIGES / (identifiant(course_id) + ".json")

def figer(rapport, marge=MARGE_MINUTES):
    chemin = chemin_fige(rapport["course_id"])

    if chemin.exists():
        document = lire(chemin)
        verifier_fige(document)
        return document

    instant = maintenant()
    depart = date_paris(rapport["depart"])
    secondes = (depart - instant).total_seconds()

    if not (0 < secondes <= marge * 60):
        return None

    if not verifier_source(rapport.get("source")):
        return None

    if sorted(m["moteur"] for m in rapport["moteurs"]) != sorted(MOTEURS):
        return None

    document = {
        "statut": "FIGE_AVANT_DEPART",
        "fige_a": instant.isoformat(),
        "rapport": rapport
    }
    document["sha256"] = empreinte(document)
    verifier_fige(document)

    FIGES.mkdir(parents=True, exist_ok=True)

    try:
        with chemin.open("x", encoding="utf-8") as f:
            json.dump(
                document, f,
                ensure_ascii=False, indent=2
            )
            f.write("\n")
    except FileExistsError:
        document = lire(chemin)
        verifier_fige(document)

    return document

def auditer(fige, arrivee):
    verifier_fige(fige)

    rapport = fige["rapport"]

    if arrivee.get("course_id") != rapport["course_id"]:
        raise ValueError("Course differente")

    if arrivee.get("statut") != "definitive":
        raise ValueError("Arrivee non definitive")

    if not verifier_source(arrivee.get("source")):
        raise ValueError("Source officielle absente")

    ordre = arrivee.get("arrivee")

    if (
        not isinstance(ordre, list)
        or len(ordre) < 5
        or any(type(n) is not int or n <= 0 for n in ordre)
        or len(set(ordre)) != len(ordre)
    ):
        raise ValueError("Arrivee invalide")

    bilans = []

    for moteur in rapport["moteurs"]:
        choix = moteur["ordre_espere"]

        bilans.append({
            "moteur": moteur["moteur"],
            "gagnant_espere": choix[0],
            "gagnant_trouve": choix[0] == ordre[0],
            "chevaux_dans_les_cinq": len(
                set(choix) & set(ordre[:5])
            ),
            "ordre_exact_cinq": choix == ordre[:5]
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": rapport["course_id"],
        "statut": "AUDIT_EFFECTUE",
        "audit_a": maintenant().isoformat(),
        "fige_sha256": fige["sha256"],
        "source_arrivee": arrivee["source"],
        "arrivee_officielle": ordre,
        "moteurs": bilans
    }

if __name__ == "__main__":
    print("X1000 PHOENIX M1-M5 : module disponible")
