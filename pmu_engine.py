#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Collecte et audit PMU."""
import json
import os
import hashlib
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
BASE = "https://online.turfinfo.api.pmu.fr/rest/client/61"
ROOT = Path("data")
ROOT.mkdir(exist_ok=True)

def maintenant():
    return datetime.now(PARIS)

def lire(nom, defaut=None):
    p = ROOT / nom
    if not p.exists():
        return defaut
    return json.loads(p.read_text(encoding="utf-8"))

def sauver(nom, donnees):
    p = ROOT / nom
    temporaire = p.with_suffix(".tmp")
    temporaire.write_text(
        json.dumps(donnees, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    os.replace(temporaire, p)

def api(chemin):
    url = BASE + chemin
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 X1000-Phoenix",
            "Accept": "application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def liste(x):
    return x if isinstance(x, list) else []

def nombre(x, defaut=0):
    try:
        return float(x)
    except (ValueError, TypeError):
        return defaut

def identite(course):
    return f"{course['date']}-R{course['reunion']}-C{course['course']}"

def extraire_courses(programme, date):
    courses = []
    for reunion in liste(programme.get("programme", {}).get("reunions")):
        rn = reunion.get("numOfficiel")
        hippo = reunion.get("hippodrome", {})
        pays = hippo.get("pays", {})
        if isinstance(pays, dict):
            pays = pays.get("code", "")
        if str(pays).upper() not in ("FRA", "FR", "FRANCE"):
            continue
        for c in liste(reunion.get("courses")):
            cn = c.get("numOrdre")
            depart = c.get("heureDepart")
            if not rn or not cn or not depart:
                continue
            courses.append({
                "date": date,
                "reunion": rn,
                "course": cn,
                "hippodrome": hippo.get("libelleCourt", ""),
                "nom": c.get("libelle", ""),
                "depart_ms": depart,
                "discipline": c.get("discipline", ""),
                "distance": c.get("distance", 0)
            })
    return courses

def extraire_partants(reponse):
    if isinstance(reponse, dict):
        reponse = reponse.get("participants", [])
    chevaux = []
    for p in liste(reponse):
        numero = p.get("numPmu")
        if not numero:
            continue
        chevaux.append({
            "numero": numero,
            "nom": p.get("nom", ""),
            "musique": str(p.get("musique", "")),
            "gains": nombre(p.get("gainCarriere")),
            "non_partant": bool(p.get("nonPartant", False)),
            "jockey": p.get("driver", p.get("jockey", "")),
            "entraineur": p.get("entraineur", "")
        })
    return chevaux

def points_forme(musique):
    """Indicateur simplifié, non probabiliste."""
    valeurs = []
    for c in musique:
        if c.isdigit():
            rang = int(c)
            if rang == 0:
                rang = 10
            valeurs.append(max(0, 11 - rang))
        if len(valeurs) >= 5:
            break
    return sum(valeurs) / len(valeurs) if valeurs else 0

def moteurs(chevaux):
    actifs = [c for c in chevaux if not c["non_partant"]]
    if len(actifs) < 5:
        return []

    max_gains = max((c["gains"] for c in actifs), default=1) or 1
    profils = {
        "M1": (0.80, 0.20),
        "M2": (0.65, 0.35),
        "M3": (0.50, 0.50),
        "M4": (0.35, 0.65),
        "M5": (0.20, 0.80)
    }
    sorties = []
    for nom, (wf, wg) in profils.items():
        classement = sorted(
            actifs,
            key=lambda c: (
                wf * points_forme(c["musique"]) / 10
                + wg * c["gains"] / max_gains
            ),
            reverse=True
        )
        selection = [c["numero"] for c in classement[:5]]
        sorties.append({
            "moteur": nom,
            "gagnant_espere": selection[0],
            "meilleur_place": selection[1],
            "ordre_espere": selection,
            "qualification": "EXPERIMENTAL",
            "validation": "DONNEES_PARTIELLES",
            "pari_retenu": None
        })
    return sorties

def horodatage(ms):
    return datetime.fromtimestamp(ms / 1000, PARIS)

def collecter(date):
    code = datetime.strptime(date, "%Y-%m-%d").strftime("%d%m%Y")
    programme = api(f"/programme/{code}?specialisation=INTERNET")
    courses = extraire_courses(programme, date)
    donnees = []
    figes = lire("figes.json", {})
    pv = lire("pv.json", {})

    for course in courses:
        cid = identite(course)
        try:
            reponse = api(
                f"/programme/{code}/R{course['reunion']}"
                f"/C{course['course']}/participants"
                "?specialisation=INTERNET"
            )
            chevaux = extraire_partants(reponse)
            course["partants"] = chevaux
            course["nombre_partants"] = sum(
                not c["non_partant"] for c in chevaux
            )
            depart = horodatage(course["depart_ms"])
            restant = (depart - maintenant()).total_seconds()
            predictions = moteurs(chevaux)

            if restant > 0 and predictions:
                pv[cid] = {
                    "course": cid,
                    "cree_a": maintenant().isoformat(),
                    "depart": depart.isoformat(),
                    "moteurs": predictions
                }

            # Verrou automatique uniquement avant départ.
            # Ne jamais modifier un FIGÉ existant.
            if 0 < restant <= 1200 and predictions and cid not in figes:
                contenu = {
                    "course": cid,
                    "fige_a": maintenant().isoformat(),
                    "depart": depart.isoformat(),
                    "moteurs": predictions
                }
                empreinte = hashlib.sha256(
                    json.dumps(contenu, sort_keys=True).encode()
                ).hexdigest()
                contenu["sha256"] = empreinte
                figes[cid] = contenu

            course["moteurs"] = (
                figes[cid]["moteurs"] if cid in figes
                else predictions if restant > 0 else []
            )
            course["statut"] = (
                "FIGE" if cid in figes
                else "PV" if restant > 0 and predictions
                else "SANS_PRONOSTIC"
            )
        except Exception as exc:
            course["statut"] = "ERREUR_SOURCE"
            course["erreur"] = str(exc)
        donnees.append(course)

    sauver("pv.json", pv)
    sauver("figes.json", figes)
    sauver("courses.json", {
        "date": date,
        "actualise": maintenant().isoformat(),
        "courses": donnees
    })
    return len(donnees)

def auditer(date):
    code = datetime.strptime(date, "%Y-%m-%d").strftime("%d%m%Y")
    figes = lire("figes.json", {})
    audits = lire("audits.json", {})

    for cid, fige in figes.items():
        if not cid.startswith(date + "-"):
            continue
        try:
            morceaux = cid.split("-")
            reunion = morceaux[-2]
            course = morceaux[-1]
            resultat = api(
                f"/programme/{code}/{reunion}/{course}"
                "/arrivee-definitive?specialisation=INTERNET"
            )
            arrivee = resultat.get("ordreArrivee", [])
            if not arrivee or not isinstance(arrivee[0], list):
                continue
            ordre = [int(x) for x in arrivee[0]]
            bilans = []
            for m in fige["moteurs"]:
                choix = m["ordre_espere"]
                bilans.append({
                    "moteur": m["moteur"],
                    "selection": choix,
                    "gagnant_correct": choix[0] == ordre[0],
                    "chevaux_top5": len(
                        set(choix) & set(ordre[:5])
                    )
                })
            audits[cid] = {
                "arrivee": ordre,
                "audite_a": maintenant().isoformat(),
                "source": "PMU",
                "fige_sha256": fige["sha256"],
                "bilans": bilans
            }
        except Exception as exc:
            print(f"Audit indisponible {cid}: {exc}")

    sauver("audits.json", audits)

def main():
    date = maintenant().date().isoformat()
    rapport = {
        "execution": maintenant().isoformat(),
        "date": date,
        "statut": "ERREUR",
        "courses": 0
    }
    try:
        rapport["courses"] = collecter(date)
        rapport["statut"] = "OK"
        auditer(date)
        auditer((maintenant() - timedelta(days=1)).date().isoformat())
    except Exception as exc:
        rapport["erreur"] = str(exc)
        print(f"ERREUR: {exc}")
    finally:
        sauver("rapport.json", rapport)
        print(json.dumps(rapport, ensure_ascii=False))
    if rapport["statut"] != "OK":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
