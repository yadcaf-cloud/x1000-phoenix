#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""X1000 PHOENIX — Intelligence hippique M1-M5.
Analyse, tableau officiel, FIGES et audits.
Aucune donnée hippique n'est inventée.
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
BASE = Path("data")
FIGES = BASE / "figes"
AUDITS = BASE / "audits"
MARGE_MINUTES = 15

MOTEURS = {
    "M1": {
        "forme": 4, "aptitude": 3,
        "regularite": 2, "entourage": 1, "valeur": 2
    },
    "M2": {
        "forme": 2, "aptitude": 4,
        "regularite": 3, "entourage": 1, "valeur": 2
    },
    "M3": {
        "forme": 2, "aptitude": 2,
        "regularite": 2, "entourage": 2, "valeur": 4
    },
    "M4": {
        "forme": 3, "aptitude": 2,
        "regularite": 3, "entourage": 3, "valeur": 1
    },
    "M5": {
        "forme": 2, "aptitude": 3,
        "regularite": 2, "entourage": 2, "valeur": 3
    },
}

CRITERES = (
    "forme", "aptitude", "regularite",
    "entourage", "valeur"
)


def maintenant():
    return dt.datetime.now(PARIS)


def lire(chemin):
    def sans_doublon(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError(
                    f"Cle JSON dupliquee: {cle}"
                )
            resultat[cle] = valeur
        return resultat

    with open(chemin, encoding="utf-8") as fichier:
        return json.load(
            fichier,
            object_pairs_hook=sans_doublon
        )


def ecrire(chemin, objet):
    chemin = Path(chemin)
    chemin.parent.mkdir(
        parents=True, exist_ok=True
    )
    temporaire = chemin.with_suffix(
        chemin.suffix + ".tmp"
    )
    temporaire.write_text(
        json.dumps(
            objet, ensure_ascii=False, indent=2,
            allow_nan=False
        ) + "\n",
        encoding="utf-8"
    )
    os.replace(temporaire, chemin)


def date_paris(valeur):
    date = dt.datetime.fromisoformat(valeur)
    if date.tzinfo is None:
        raise ValueError(
            "Date sans fuseau horaire"
        )
    return date.astimezone(PARIS)


def identifiant(valeur):
    return re.sub(
        r"[^a-zA-Z0-9_-]", "_", str(valeur)
    )


def empreinte(objet):
    brut = json.dumps(
        objet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(brut).hexdigest()


def valider_course(course):
    if not isinstance(course, dict):
        raise ValueError("Course JSON invalide")

    for champ in (
        "id", "depart", "hippodrome", "partants"
    ):
        if not course.get(champ):
            raise ValueError(
                f"Champ obligatoire absent: {champ}"
            )

    depart = date_paris(course["depart"])

    chevaux = course["partants"]
    if not isinstance(chevaux, list):
        raise ValueError("Partants invalides")

    numeros = []
    actifs = []

    for cheval in chevaux:
        numero = cheval.get("numero")

        if type(numero) is not int or numero <= 0:
            raise ValueError("Numero invalide")

        if numero in numeros:
            raise ValueError("Numero duplique")

        numeros.append(numero)

        if cheval.get("non_partant", False):
            continue

        notes = cheval.get("notes", {})

        if not isinstance(notes, dict):
            raise ValueError("Notes invalides")

        for critere in CRITERES:
            note = notes.get(critere)

            if (
                type(note) not in (int, float)
                or not math.isfinite(note)
                or not 0 <= note <= 10
            ):
                raise ValueError(
                    f"Note invalide: cheval "
                    f"{numero}, {critere}"
                )

        actifs.append(cheval)

    if len(actifs) < 2:
        raise ValueError(
            "Moins de deux partants valides"
        )

    return depart, actifs


def analyser(course):
    depart, chevaux = valider_course(course)
    horloge = maintenant()
    rapports = []

    for nom, poids in MOTEURS.items():
        classement = []

        for cheval in chevaux:
            notes = cheval["notes"]

            score = sum(
                notes[c] * poids[c]
                for c in CRITERES
            ) / sum(poids.values())

            classement.append({
                "numero": cheval["numero"],
                "score": round(score, 3)
            })

        classement.sort(
            key=lambda x: (
                -x["score"], x["numero"]
            )
        )

        ordre = [
            c["numero"] for c in classement
        ]

        ecart = (
            classement[0]["score"]
            - classement[1]["score"]
        )

        confiance = (
            "FORTE" if ecart >= 1.5
            else "MOYENNE" if ecart >= 0.5
            else "FAIBLE"
        )

        rapports.append({
            "moteur": nom,
            "gagnant_espere": ordre[0],
            "meilleur_place": ordre[1],
            "ordre_espere": ordre,
            "pari_retenu": (
                "AUCUN - etude indicative"
            ),
            "qualification": (
                "VERT" if confiance != "FAIBLE"
                else "JAUNE"
            ),
            "validation": "INDICATIF",
            "confiance_heuristique": confiance,
            "ecart_scores": round(ecart, 3),
            "scores": classement,
            "heure_paris": horloge.isoformat()
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": course["id"],
        "hippodrome": course["hippodrome"],
        "depart": depart.isoformat(),
        "source": course.get("source"),
        "analyse_a": horloge.isoformat(),
        "nombre_partants": len(chevaux),
        "moteurs": rapports,
        "statut": "ANALYSE_INDICATIVE",
        "avertissement": (
            "Scores heuristiques non calibres. "
            "Aucune victoire ni pari garanti."
        )
    }


def chemin_fige(course_id):
    return FIGES / (
        identifiant(course_id) + ".json"
    )


def figer(rapport, marge=MARGE_MINUTES):
    FIGES.mkdir(
        parents=True, exist_ok=True
    )

    chemin = chemin_fige(
        rapport["course_id"]
    )

    if chemin.exists():
        print("FIGE deja existant: conservation")
        return lire(chemin)

    horloge = maintenant()
    depart = date_paris(rapport["depart"])

    if horloge >= depart:
        print("FIGE refuse: depart atteint")
        return None

    if (depart - horloge).total_seconds() > (
        marge * 60
    ):
        print("FIGE en attente du depart")
        return None

    if not rapport.get("source"):
        print("FIGE refuse: source absente")
        return None

    if any(
        m["validation"] != "INDICATIF"
        for m in rapport["moteurs"]
    ):
        print("FIGE refuse: analyse incomplete")
        return None

    document = {
        "statut": "FIGE_AVANT_DEPART",
        "fige_a": horloge.isoformat(),
        "rapport": rapport
    }

    document["sha256"] = empreinte(document)

    # Creation exclusive: aucun ecrasement
    # d'un FIGE deja enregistre.
    contenu = json.dumps(
        document, ensure_ascii=False, indent=2
    ) + "\n"

    try:
        with chemin.open(
            "x", encoding="utf-8"
        ) as fichier:
            fichier.write(contenu)
    except FileExistsError:
        return lire(chemin)

    print("FIGE cree:", chemin)
    return document


def auditer(fige, arrivee):
    contenu = {
        cle: valeur
        for cle, valeur in fige.items()
        if cle != "sha256"
    }

    if (
        empreinte(contenu)
        != fige.get("sha256")
    ):
        raise ValueError(
            "Integrite du FIGE non valide"
        )

    rapport = fige["rapport"]

    if (
        arrivee.get("course_id")
        != rapport["course_id"]
    ):
        raise ValueError(
            "Identifiant de course different"
        )

    if (
        arrivee.get("statut") != "definitive"
        or not arrivee.get("source")
    ):
        raise ValueError(
            "Arrivee definitive sourcee requise"
        )

    depart = date_paris(rapport["depart"])
    fige_a = date_paris(fige["fige_a"])

    if fige_a >= depart:
        raise ValueError(
            "FIGE non anterieur au depart"
        )

    ordre = arrivee.get("arrivee")

    if (
        not isinstance(ordre, list)
        or not ordre
        or any(
            type(n) is not int or n <= 0
            for n in ordre
        )
        or len(ordre) != len(set(ordre))
    ):
        raise ValueError(
            "Arrivee officielle invalide"
        )

    analyses = []

    for moteur in rapport["moteurs"]:
        selection = moteur["ordre_espere"]

        analyses.append({
            "moteur": moteur["moteur"],
            "gagnant_espere": (
                moteur["gagnant_espere"]
            ),
            "gagnant_trouve": (
                selection[0] == ordre[0]
            ),
            "meilleur_place": (
                moteur["meilleur_place"]
            ),
            "chevaux_dans_les_cinq": len(
                set(selection[:5])
                & set(ordre[:5])
            ),
            "ordre_exact_cinq": (
                selection[:5] == ordre[:5]
                if len(ordre) >= 5
                else False
            )
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": rapport["course_id"],
        "statut": "AUDIT_EFFECTUE",
        "audit_a": maintenant().isoformat(),
        "fige_sha256": fige["sha256"],
        "source_arrivee": arrivee["source"],
        "arrivee_officielle": ordre,
        "moteurs": analyses
    }


def afficher_tableau(rapport):
    print("\n" + "=" * 64)
    print("X1000 PHOENIX - TABLEAU OFFICIEL")
    print("=" * 64)
    print("Course:", rapport["course_id"])
    print("Hippodrome:", rapport["hippodrome"])
    print("Depart:", rapport["depart"])
    print("-" * 64)

    for moteur in rapport["moteurs"]:
        print(
            moteur["moteur"],
            "| Gagnant:", moteur["gagnant_espere"],
            "| Place:", moteur["meilleur_place"]
        )
        print(
            "Ordre:",
            "-".join(
                map(str, moteur["ordre_espere"][:5])
            )
        )
        print(
            "Qualification:",
            moteur["qualification"],
            "| Validation:",
            moteur["validation"]
        )
        print(
            "Pari:", moteur["pari_retenu"]
        )
        print("-" * 64)


def traiter_audit(chemin):
    arrivee = lire(chemin)

    course_id = arrivee.get("course_id")
    if not course_id:
        raise ValueError(
            "Identifiant d'arrivee absent"
        )

    chemin_source = chemin_fige(course_id)

    if not chemin_source.exists():
        print(
            "Audit en attente: aucun FIGE",
            course_id
        )
        return None

    resultat = auditer(
        lire(chemin_source), arrivee
    )

    destination = AUDITS / (
        identifiant(course_id) + ".json"
    )

    if destination.exists():
        precedent = lire(destination)
        if (
            precedent.get("fige_sha256")
            == resultat["fige_sha256"]
            and precedent.get("arrivee_officielle")
            == resultat["arrivee_officielle"]
            and precedent.get("source_arrivee")
            == resultat["source_arrivee"]
        ):
            print("Audit deja enregistre")
            return precedent

    ecrire(destination, resultat)
    print("Audit enregistre:", destination)
    return resultat


def main():
    parser = argparse.ArgumentParser(
        description="X1000 PHOENIX M1-M5"
    )

    parser.add_argument(
        "--input", default="data/course.json"
    )
    parser.add_argument(
        "--output", default="data/latest.json"
    )
    parser.add_argument(
        "--figer", action="store_true"
    )
    parser.add_argument(
        "--auto", action="store_true"
    )
    parser.add_argument(
        "--audit", default=None
    )
    parser.add_argument(
        "--marge", type=int,
        default=MARGE_MINUTES
    )

    args = parser.parse_args()

    if not 1 <= args.marge <= 120:
        parser.error(
            "La marge doit etre entre 1 et 120"
        )

    FIGES.mkdir(
        parents=True, exist_ok=True
    )
    AUDITS.mkdir(
        parents=True, exist_ok=True
    )

    if args.audit:
        traiter_audit(args.audit)
        return

    source = Path(args.input)

    if not source.exists():
        print("Aucune course disponible")
    else:
        rapport = analyser(lire(source))
        ecrire(args.output, rapport)
        afficher_tableau(rapport)

        if args.figer or args.auto:
            figer(rapport, args.marge)

    if args.auto:
        dossier = BASE / "arrivees"
        if dossier.exists():
            for fichier in sorted(
                dossier.glob("*.json")
            ):
                traiter_audit(fichier)


if __name__ == "__main__":
    main()
