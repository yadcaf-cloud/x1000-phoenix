#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — orchestration M1–M5 et archives FIGÉES protégées.

Commandes : python phoenix.py ; python phoenix.py --self-test
Aucun pari heuristique n'est automatiquement transformé en FIGÉ.
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
FIGES = DATA / "figes"
PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def maintenant():
    return dt.datetime.now(PARIS).isoformat()


def date_paris():
    return dt.datetime.now(PARIS).date().isoformat()


def identifiant(course_id):
    if not isinstance(course_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", course_id):
        raise ValueError("Identifiant de course invalide (ASCII, 1 à 120 caractères)")
    return course_id


def chemin_fige(course_id):
    return FIGES / (identifiant(course_id) + ".json")


def _sans_doublons(paires):
    resultat = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError(f"Clé JSON dupliquée : {cle}")
        resultat[cle] = valeur
    return resultat


def _constante_invalide(valeur):
    raise ValueError(f"Constante JSON non autorisée : {valeur}")


def lire(chemin):
    with Path(chemin).open("r", encoding="utf-8") as fichier:
        return json.load(fichier, object_pairs_hook=_sans_doublons,
                         parse_constant=_constante_invalide)


def rapport_fige(document):
    if not isinstance(document, dict):
        raise ValueError("Document FIGÉ non objet")
    rapport = document.get("rapport")
    if not isinstance(rapport, dict):
        contenu = document.get("contenu")
        rapport = contenu.get("analyse") if isinstance(contenu, dict) else None
    if not isinstance(rapport, dict):
        raise ValueError("Rapport FIGÉ absent ou invalide")
    return rapport


def empreinte_rapport(rapport):
    if not isinstance(rapport, dict):
        raise ValueError("Rapport invalide")
    donnees = json.dumps(rapport, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(donnees).hexdigest()


def controle_fige(document):
    resultat = {"integrite": "INVALIDE", "course_id": None, "moteurs": [],
                "empreinte_presente": False, "empreinte_concordante": False,
                "message": ""}
    try:
        rapport = rapport_fige(document)
        cid = rapport.get("course_id", rapport.get("id"))
        identifiant(cid)
        resultat["course_id"] = cid
        moteurs = rapport.get("moteurs")
        if not isinstance(moteurs, list) or not moteurs:
            raise ValueError("Liste des moteurs absente ou vide")
        noms = []
        for moteur in moteurs:
            if not isinstance(moteur, dict) or moteur.get("moteur") not in MOTEURS:
                raise ValueError("Moteur inconnu ou structure invalide")
            noms.append(moteur["moteur"])
        if len(noms) != len(set(noms)):
            raise ValueError("Moteurs dupliqués")
        resultat["moteurs"] = sorted(noms)
        sha = document.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            resultat["integrite"] = "NON_VERIFIABLE"
            resultat["message"] = "Empreinte SHA256 absente ou format historique inconnu"
            return resultat
        resultat["empreinte_presente"] = True
        concordance = hmac.compare_digest(empreinte_rapport(rapport), sha.lower())
        resultat["empreinte_concordante"] = concordance
        resultat["integrite"] = "VERIFIE" if concordance else "NON_VERIFIABLE"
        resultat["message"] = ("SHA256 canonique concordant" if concordance else
                               "SHA256 non concordant : format historique différent ou modification possible")
    except (ValueError, TypeError, OverflowError) as erreur:
        resultat["message"] = str(erreur)
    return resultat


def verifier_fige(document, exiger_integrite=False):
    controle = controle_fige(document)
    if controle["integrite"] == "INVALIDE" or (exiger_integrite and controle["integrite"] != "VERIFIE"):
        raise ValueError(controle["message"])
    return True


def _est_fige(chemin):
    chemin = Path(chemin).resolve()
    dossier = FIGES.resolve()
    return chemin == dossier or dossier in chemin.parents


def ecrire(chemin, document):
    chemin = Path(chemin)
    if chemin.is_symlink():
        raise ValueError("Écriture sur lien symbolique interdite")
    if _est_fige(chemin):
        if chemin.suffix.lower() != ".json":
            raise ValueError("Archive FIGÉE : extension .json obligatoire")
        verifier_fige(document, exiger_integrite=True)
        rapport = rapport_fige(document)
        if chemin.name != identifiant(rapport.get("course_id", rapport.get("id"))) + ".json":
            raise ValueError("Nom de fichier FIGÉ incohérent avec la course")
    contenu = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if _est_fige(chemin):
        # O_EXCL empêche un écrasement même entre deux exécutions concurrentes.
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fichier:
                fichier.write(contenu)
                fichier.flush()
                os.fsync(fichier.fileno())
        except Exception:
            # Une erreur d'écriture laisse le fichier pour examen : ne jamais supprimer une archive.
            raise
        return chemin
    temporaire = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=chemin.parent,
                                         prefix=".x1000_", suffix=".tmp", delete=False) as fichier:
            temporaire = Path(fichier.name)
            fichier.write(contenu)
            fichier.flush()
            os.fsync(fichier.fileno())
        os.replace(temporaire, chemin)
    finally:
        if temporaire is not None and temporaire.exists():
            temporaire.unlink()
    return chemin


def statut_fige(document):
    verifier_fige(document)
    moteurs = rapport_fige(document)["moteurs"]
    return ("PARI_OFFICIEL_FIGE" if any(
        m.get("validation") == "OFFICIEL_VALIDE" and m.get("pari_retenu") not in (None, "", [], {})
        for m in moteurs) else "FIGE_INDICATIF")


def bilan_fige(document):
    verifier_fige(document)
    controle = controle_fige(document)
    return {"course_id": controle["course_id"], "sha256": document.get("sha256"),
            "integrite": controle["integrite"], "message_integrite": controle["message"],
            "statut": statut_fige(document), "moteurs": rapport_fige(document)["moteurs"],
            "historique_modifie": False}


def diagnostic_moteurs():
    try:
        from analyser_moteurs import analyser as analyse_reelle, MOTEURS as noms
        raccordes = callable(analyse_reelle) and tuple(noms) == MOTEURS
    except (ImportError, AttributeError):
        raccordes = False
    return {**{nom: ("HEURISTIQUE_RACCORDEE_NON_VALIDEE" if raccordes else "NON_RACCORDE")
               for nom in MOTEURS}, "analyse_reelle": raccordes,
            "nouveaux_figes": False, "heure_paris": maintenant()}


def analyser(course):
    from analyser_moteurs import analyser as analyse_moteurs
    return analyse_moteurs(course)


def figer(analyse):
    """Retourne uniquement une archive existante ; ne crée aucun FIGÉ heuristique."""
    if not isinstance(analyse, dict):
        raise ValueError("Analyse invalide")
    cid = identifiant(analyse.get("course_id", analyse.get("id")))
    chemin = chemin_fige(cid)
    if not chemin.is_file():
        return None
    document = lire(chemin)
    verifier_fige(document)
    rapport = rapport_fige(document)
    if rapport.get("course_id", rapport.get("id")) != cid:
        raise ValueError("FIGÉ historique associé à une autre course")
    return document


def auditer_figes_historiques():
    resultat = {"verifies": 0, "non_verifiables": 0, "invalides": 0,
                "documents": [], "heure_paris": maintenant()}
    if not FIGES.is_dir():
        return resultat
    for chemin in sorted(FIGES.glob("*.json")):
        try:
            controle = controle_fige(lire(chemin))
        except (OSError, ValueError, TypeError) as erreur:
            controle = {"integrite": "INVALIDE", "message": str(erreur), "course_id": None}
        cle = {"VERIFIE": "verifies", "NON_VERIFIABLE": "non_verifiables",
               "INVALIDE": "invalides"}[controle["integrite"]]
        resultat[cle] += 1
        resultat["documents"].append({"fichier": chemin.name, **controle})
    return resultat


def self_test():
    cid = "2026-10-29-R1-C1"
    rapport = {"course_id": cid, "moteurs": [{"moteur": "M1", "validation": "NON_FIGE"}]}
    document = {"rapport": rapport, "sha256": empreinte_rapport(rapport)}
    assert controle_fige(document)["integrite"] == "VERIFIE"
    assert statut_fige(document) == "FIGE_INDICATIF"
    assert identifiant(cid) == cid
    assert controle_fige({**document, "sha256": "0" * 64})["integrite"] == "NON_VERIFIABLE"
    assert controle_fige({"rapport": rapport})["integrite"] == "NON_VERIFIABLE"
    assert chemin_fige(cid).name == cid + ".json"
    print("X1000 PHOENIX : tests locaux OK (aucun fichier historique modifié)")


def main():
    parser = argparse.ArgumentParser(description="X1000 PHOENIX - Archives et diagnostic M1-M5")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    print(json.dumps({"moteurs": diagnostic_moteurs(),
                      "archives": auditer_figes_historiques()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
