#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — M1 à M5 : analyse, FIGÉS, audits."""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")

MOTEURS = {
    "M1": {"forme": 4, "aptitude": 3, "regularite": 2, "entourage": 1, "valeur": 2},
    "M2": {"forme": 2, "aptitude": 4, "regularite": 3, "entourage": 1, "valeur": 2},
    "M3": {"forme": 2, "aptitude": 2, "regularite": 2, "entourage": 2, "valeur": 4},
    "M4": {"forme": 3, "aptitude": 2, "regularite": 3, "entourage": 3, "valeur": 1},
    "M5": {"forme": 2, "aptitude": 3, "regularite": 2, "entourage": 2, "valeur": 3},
}

CRITERES = ("forme", "aptitude", "regularite", "entourage", "valeur")


def lire(chemin):
    def uniques(paires):
        d = {}
        for k, v in paires:
            if k in d:
                raise ValueError(f"Clé JSON dupliquée: {k}")
            d[k] = v
        return d

    with open(chemin, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=uniques)


def ecrire(chemin, objet):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    temporaire.write_text(
        json.dumps(objet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporaire.replace(chemin)


def horodatage(texte):
    valeur = dt.datetime.fromisoformat(texte)
    if valeur.tzinfo is None:
        raise ValueError("Horaire sans fuseau: fournir +01:00 ou +02:00")
    return valeur.astimezone(TZ)


def analyser(course):
    for champ in ("id", "depart", "hippodrome", "partants"):
        if champ not in course:
            raise ValueError(f"Champ manquant: {champ}")

    depart = horodatage(course["depart"])
    chevaux = course["partants"]

    if not isinstance(chevaux, list) or not chevaux:
        raise ValueError("Liste de partants vide")

    numeros = [c["numero"] for c in chevaux]

    if len(numeros) != len(set(numeros)) or any(
        type(n) is not int or n <= 0 for n in numeros
    ):
        raise ValueError("Numéros invalides ou dupliqués")

    actifs = [
        c for c in chevaux if not c.get("non_partant", False)
    ]
    rapports = []

    for nom, poids in MOTEURS.items():
        notes = []

        for cheval in actifs:
            valeurs = cheval.get("notes", {})

            if not all(
                type(valeurs.get(k)) in (int, float)
                and 0 <= valeurs[k] <= 10
                for k in CRITERES
            ):
                continue

            score = round(
                sum(valeurs[k] * poids[k] for k in CRITERES)
                / sum(poids.values()),
                3,
            )

            notes.append({
                "numero": cheval["numero"],
                "score": score,
            })

        notes.sort(key=lambda c: (-c["score"], c["numero"]))

        complet = len(notes) == len(actifs) and len(actifs) >= 2

        rapports.append({
            "moteur": nom,
            "qualification": "VERT" if complet else "JAUNE",
            "validation": (
                "INDICATIF" if complet
                else "DONNEES_INSUFFISANTES"
            ),
            "gagnant_espere": (
                notes[0]["numero"] if complet else None
            ),
            "meilleur_place": (
                notes[1]["numero"] if complet else None
            ),
            "ordre_espere": (
                [x["numero"] for x in notes] if complet else []
            ),
            "pari_retenu": "AUCUN - étude indicative",
            "scores": notes if complet else [],
            "heure_paris": dt.datetime.now(TZ).isoformat(
                timespec="seconds"
            ),
        })

    return {
        "course_id": course["id"],
        "hippodrome": course["hippodrome"],
        "depart": depart.isoformat(),
        "source": course.get("source"),
        "nombre_partants": len(actifs),
        "moteurs": rapports,
        "avertissement": (
            "Scores heuristiques, non probabilités "
            "de victoire; aucun pari garanti."
        ),
    }


def figer(rapport, chemin, maintenant=None):
    maintenant = maintenant or dt.datetime.now(TZ)
    depart = horodatage(rapport["depart"])

    if maintenant >= depart:
        raise ValueError(
            "FIGÉ interdit après ou à l’heure de départ"
        )

    if not rapport.get("source"):
        raise ValueError(
            "FIGÉ interdit sans source de données identifiée"
        )

    if any(
        m["validation"] != "INDICATIF"
        for m in rapport["moteurs"]
    ):
        raise ValueError(
            "FIGÉ interdit: données insuffisantes"
        )

    chemin = Path(chemin)

    if chemin.exists():
        raise FileExistsError(
            "FIGÉ existant: modification interdite"
        )

    document = {
        "statut": "FIGE_AVANT_DEPART",
        "fige_a": maintenant.isoformat(),
        "rapport": rapport,
    }

    brut = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    document["sha256"] = hashlib.sha256(brut).hexdigest()

    ecrire(chemin, document)
    return document


def auditer(fige, arrivee):
    contenu = {
        k: v for k, v in fige.items() if k != "sha256"
    }

    brut = json.dumps(
        contenu,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    if hashlib.sha256(brut).hexdigest() != fige["sha256"]:
        raise ValueError("Empreinte FIGÉ incorrecte")

    if (
        arrivee.get("statut") != "definitive"
        or not arrivee.get("source")
    ):
        raise ValueError(
            "Arrivée officielle définitive et source requises"
        )

    if (
        arrivee.get("course_id")
        != fige["rapport"]["course_id"]
    ):
        raise ValueError(
            "Identifiants de course différents"
        )

    ordre = arrivee.get("arrivee")

    if (
        not isinstance(ordre, list)
        or not ordre
        or len(ordre) != len(set(ordre))
    ):
        raise ValueError("Arrivée invalide")

    return {
        "course_id": arrivee["course_id"],
        "source": arrivee["source"],
        "arrivee": ordre,
        "moteurs": [
            {
                "moteur": m["moteur"],
                "gagnant_trouve": (
                    m["gagnant_espere"] == ordre[0]
                ),
                "chevaux_dans_les_cinq": len(
                    set(m["ordre_espere"][:5])
                    & set(ordre[:5])
                ),
            }
            for m in fige["rapport"]["moteurs"]
        ],
    }


def main():
    p = argparse.ArgumentParser(
        description="X1000 PHOENIX M1–M5"
    )
    p.add_argument(
        "--input", default="data/course.json"
    )
    p.add_argument(
        "--output", default="data/latest.json"
    )
    p.add_argument("--figer", action="store_true")
    p.add_argument(
        "--audit",
        help="Fichier arrivée définitive JSON",
    )
    a = p.parse_args()

    if a.audit:
        figes = sorted(
            Path("data/figes").glob("*.json")
        )
        arrivee = lire(a.audit)

        correspondants = [
            f for f in figes
            if lire(f)["rapport"]["course_id"]
            == arrivee.get("course_id")
        ]

        if not correspondants:
            raise ValueError(
                "Aucun FIGÉ correspondant"
            )

        resultat = auditer(
            lire(correspondants[0]), arrivee
        )
        ecrire("data/audit.json", resultat)
        print(json.dumps(
            resultat, ensure_ascii=False, indent=2
        ))
        return

    rapport = analyser(lire(a.input))
    ecrire(a.output, rapport)

    if a.figer:
        ident = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in rapport["course_id"]
        )
        figer(
            rapport,
            Path("data/figes") / (ident + ".json"),
        )

    print(json.dumps(
        rapport, ensure_ascii=False, indent=2
    ))


if __name__ == "__main__":
    main()
