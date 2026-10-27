
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - M1 à M5, FIGÉS et audits vérifiables."""

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
CRITERES = ("forme", "aptitude", "regularite", "entourage", "valeur")

MOTEURS = {
    "M1": dict(zip(CRITERES, (4, 3, 2, 1, 2))),
    "M2": dict(zip(CRITERES, (2, 4, 3, 1, 2))),
    "M3": dict(zip(CRITERES, (2, 2, 2, 2, 4))),
    "M4": dict(zip(CRITERES, (3, 2, 3, 3, 1))),
    "M5": dict(zip(CRITERES, (2, 3, 2, 2, 3))),
}

def maintenant():
    return dt.datetime.now(PARIS)

def lire(path):
    def verifier(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError(f"Clé JSON dupliquée : {cle}")
            resultat[cle] = valeur
        return resultat
    with open(path, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=verifier)

def ecrire(path, objet):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporaire = path.with_name(path.name + ".tmp")
    temporaire.write_text(
        json.dumps(objet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    os.replace(temporaire, path)

def date_paris(valeur):
    d = dt.datetime.fromisoformat(valeur)
    if d.tzinfo is None:
        raise ValueError("Date sans fuseau horaire")
    return d.astimezone(PARIS)

def empreinte(objet):
    brut = json.dumps(
        objet, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
        allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(brut).hexdigest()

def identifiant(texte):
    valeur = re.sub(r"[^a-zA-Z0-9_-]", "_", str(texte))
    if not valeur or len(valeur) > 120:
        raise ValueError("Identifiant de course invalide")
    return valeur

def analyser(course):
    for cle in ("id", "depart", "hippodrome", "partants"):
        if cle not in course:
            raise ValueError(f"Champ absent : {cle}")

    if not isinstance(course["id"], str) or not course["id"]:
        raise ValueError("ID invalide")

    depart = date_paris(course["depart"])
    chevaux = course["partants"]

    if not isinstance(chevaux, list) or not chevaux:
        raise ValueError("Aucun partant")

    numeros = []
    for cheval in chevaux:
        n = cheval.get("numero")
        if type(n) is not int or n <= 0 or n in numeros:
            raise ValueError("Numéro de cheval invalide ou dupliqué")
        numeros.append(n)
        if type(cheval.get("non_partant", False)) is not bool:
            raise ValueError("Statut non-partant invalide")

    actifs = [
        c for c in chevaux if not c.get("non_partant", False)
    ]
    resultats = []

    for nom, poids in MOTEURS.items():
        classement = []

        for cheval in actifs:
            notes = cheval.get("notes")
            if not isinstance(notes, dict):
                continue

            if not all(
                type(notes.get(k)) in (int, float)
                and math.isfinite(notes[k])
                and 0 <= notes[k] <= 10
                for k in CRITERES
            ):
                continue

            score = sum(
                notes[k] * poids[k] for k in CRITERES
            ) / sum(poids.values())

            classement.append({
                "numero": cheval["numero"],
                "score": round(score, 4)
            })

        classement.sort(
            key=lambda x: (-x["score"], x["numero"])
        )

        complet = (
            len(actifs) >= 2
            and len(classement) == len(actifs)
            and bool(course.get("source"))
            and not str(course["id"]).startswith("DEMO")
        )

        ordre = (
            [c["numero"] for c in classement]
            if complet else []
        )

        resultats.append({
            "moteur": nom,
            "qualification": "VERT" if complet else "JAUNE",
            "validation": (
                "INDICATIF" if complet
                else "DONNEES_INSUFFISANTES"
            ),
            "gagnant_espere": ordre[0] if ordre else None,
            "meilleur_place": ordre[1] if len(ordre) > 1 else None,
            "ordre_espere": ordre,
            "pari_retenu": "AUCUN - étude indicative",
            "scores": classement if complet else [],
            "heure_paris": maintenant().isoformat()
        })

    return {
        "course_id": course["id"],
        "hippodrome": course["hippodrome"],
        "depart": depart.isoformat(),
        "source": course.get("source"),
        "nombre_partants": len(actifs),
        "non_partants": [
            c["numero"] for c in chevaux
            if c.get("non_partant", False)
        ],
        "moteurs": resultats,
        "avertissement": (
            "Scores heuristiques, non probabilités. "
            "Aucun résultat ni gain garanti."
        )
    }

def figer(rapport, chemin, instant=None):
    instant = instant or maintenant()
    depart = date_paris(rapport["depart"])
    chemin = Path(chemin)

    if chemin.exists():
        raise FileExistsError("FIGÉ déjà existant")

    if instant >= depart:
        raise ValueError("Départ déjà atteint")

    if not rapport.get("source"):
        raise ValueError("Source absente")

    if len(rapport.get("moteurs", [])) != 5:
        raise ValueError("Cinq moteurs requis")

    if any(
        m["validation"] != "INDICATIF"
        for m in rapport["moteurs"]
    ):
        raise ValueError("Données insuffisantes")

    document = {
        "statut": "FIGE_AVANT_DEPART",
        "fige_a": instant.isoformat(),
        "rapport": rapport
    }
    document["sha256"] = empreinte(document)

    chemin.parent.mkdir(parents=True, exist_ok=True)
    # Création exclusive : ne jamais écraser un FIGÉ.
    with open(chemin, "x", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return document

def verifier_fige(document):
    if document.get("statut") != "FIGE_AVANT_DEPART":
        raise ValueError("Statut FIGÉ invalide")

    original = {
        k: v for k, v in document.items()
        if k != "sha256"
    }
    if empreinte(original) != document.get("sha256"):
        raise ValueError("Empreinte SHA256 incorrecte")

    instant = date_paris(document["fige_a"])
    depart = date_paris(document["rapport"]["depart"])

    if instant >= depart:
        raise ValueError("FIGÉ non antérieur au départ")

    return True

def auditer(document, arrivee):
    verifier_fige(document)

    if arrivee.get("statut") != "definitive":
        raise ValueError("Arrivée non définitive")

    if not arrivee.get("source"):
        raise ValueError("Source officielle absente")

    if arrivee.get("course_id") != document["rapport"]["course_id"]:
        raise ValueError("Courses différentes")

    ordre = arrivee.get("arrivee")
    if (
        not isinstance(ordre, list)
        or not ordre
        or any(type(n) is not int or n <= 0 for n in ordre)
        or len(ordre) != len(set(ordre))
    ):
        raise ValueError("Arrivée invalide")

    controles = []
    for moteur in document["rapport"]["moteurs"]:
        selection = moteur["ordre_espere"]
        controles.append({
            "moteur": moteur["moteur"],
            "gagnant_trouve": selection[0] == ordre[0],
            "chevaux_dans_les_cinq": len(
                set(selection[:5]) & set(ordre[:5])
            ),
            "ordre_exact": selection[:5] == ordre[:5]
        })

    return {
        "course_id": arrivee["course_id"],
        "statut": "AUDIT_VERIFIE",
        "audite_a": maintenant().isoformat(),
        "source": arrivee["source"],
        "arrivee": ordre,
        "sha256_fige": document["sha256"],
        "moteurs": controles
    }

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/course.json")
    p.add_argument("--output", default="data/latest.json")
    p.add_argument("--figer", action="store_true")
    p.add_argument("--audit")
    a = p.parse_args()

    if a.audit:
        arrivee = lire(a.audit)
        chemin = DATA / "figes" / (
            identifiant(arrivee["course_id"]) + ".json"
        )
        resultat = auditer(lire(chemin), arrivee)
        ecrire(
            DATA / "audits" / chemin.name,
            resultat
        )
    else:
        resultat = analyser(lire(a.input))
        ecrire(a.output, resultat)
        if a.figer:
            figer(
                resultat,
                DATA / "figes" / (
                    identifiant(resultat["course_id"]) + ".json"
                )
            )

    print(json.dumps(resultat, ensure_ascii=False, indent=2))
