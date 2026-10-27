
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — collecte PMU, PV, FIGÉS et audits traçables.

Ne crée jamais de course ni de résultat fictif. Les scores sont expérimentaux.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo('Europe/Paris')
BASE = 'https://online.turfinfo.api.pmu.fr/rest/client/61'
ROOT = Path('data')
ROOT.mkdir(parents=True, exist_ok=True)


def maintenant():
    return datetime.now(PARIS)


def lire(nom, defaut=None):
    chemin = ROOT / nom
    if not chemin.exists():
        return defaut
    return json.loads(chemin.read_text(encoding='utf-8'))


def sauver(nom, contenu):
    chemin = ROOT / nom
    temporaire = chemin.with_name(chemin.name + '.tmp')
    temporaire.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporaire, chemin)


def api(chemin):
    req = urllib.request.Request(BASE + chemin, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; X1000-Phoenix/1.1)',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=25) as reponse:
        return json.load(reponse)


def liste(obj):
    return obj if isinstance(obj, list) else []


def entier(obj, defaut=None):
    try:
        return int(obj)
    except (ValueError, TypeError):
        return defaut


def nombre(obj, defaut=0.0):
    try:
        return float(obj)
    except (ValueError, TypeError):
        return defaut


def texte(obj):
    if isinstance(obj, dict):
        return str(obj.get('libelle') or obj.get('nom') or obj.get('code') or '')
    return str(obj or '')


def identite(course):
    return f"{course['date']}-R{course['reunion']}-C{course['course']}"


def extraire_courses(programme, date):
    if not isinstance(programme, dict):
        raise ValueError('Programme PMU invalide')
    bloc = programme.get('programme', programme)
    reunions = bloc.get('reunions') if isinstance(bloc, dict) else None
    if not isinstance(reunions, list):
        raise ValueError('Champ reunions absent ou invalide')
    courses = []
    for reunion in reunions:
        if not isinstance(reunion, dict):
            continue
        rn = entier(reunion.get('numOfficiel') or reunion.get('numReunion'))
        hippo = reunion.get('hippodrome') or {}
        if not isinstance(hippo, dict):
            hippo = {'libelleCourt': texte(hippo)}
        pays = hippo.get('pays') or reunion.get('pays')
        if isinstance(pays, dict):
            pays = pays.get('code') or pays.get('libelle')
        pays = str(pays or '').strip().upper()
        # Ne pas supposer qu'une réunion sans pays est française.
        if pays not in ('FR', 'FRA', 'FRANCE'):
            continue
        for c in liste(reunion.get('courses')):
            if not isinstance(c, dict):
                continue
            cn = entier(c.get('numOrdre') or c.get('numCourse'))
            depart = entier(c.get('heureDepart'))
            if not rn or not cn or not depart:
                continue
            courses.append({
                'date': date, 'reunion': rn, 'course': cn,
                'hippodrome': texte(hippo.get('libelleCourt') or hippo.get('libelleLong')),
                'nom': texte(c.get('libelle')),
                'depart_ms': depart,
                'discipline': texte(c.get('discipline')),
                'distance': nombre(c.get('distance')),
                'source': 'PMU',
            })
    return courses


def extraire_partants(reponse):
    if isinstance(reponse, dict):
        reponse = reponse.get('participants')
    if not isinstance(reponse, list):
        raise ValueError('Liste de participants absente ou invalide')
    chevaux = []
    numeros = set()
    for p in reponse:
        if not isinstance(p, dict):
            continue
        numero = entier(p.get('numPmu'))
        if not numero or numero in numeros:
            continue
        numeros.add(numero)
        chevaux.append({
            'numero': numero,
            'nom': texte(p.get('nom')),
            'musique': texte(p.get('musique')),
            'gains': nombre(p.get('gainCarriere')),
            'non_partant': p.get('nonPartant') is True,
            'jockey': texte(p.get('driver') or p.get('jockey')),
            'entraineur': texte(p.get('entraineur')),
        })
    return chevaux


def points_forme(musique):
    # Les chiffres de musique sont un indicateur sommaire, non une probabilité.
    rangs = re.findall(r'\d', musique or '')[:5]
    return sum(max(0, 11 - (10 if x == '0' else int(x))) for x in rangs) / len(rangs) if rangs else 0


def moteurs(chevaux):
    actifs = [c for c in chevaux if not c['non_partant']]
    if len(actifs) < 5 or sum(bool(c['musique']) for c in actifs) < 5:
        return []
    plafond = max((c['gains'] for c in actifs), default=0)
    profils = {'M1': (.80, .20), 'M2': (.65, .35), 'M3': (.50, .50),
               'M4': (.35, .65), 'M5': (.20, .80)}
    sorties = []
    for nom, (wf, wg) in profils.items():
        ordre = sorted(actifs, key=lambda c: (
            -(wf * points_forme(c['musique']) / 10 +
              wg * (c['gains'] / plafond if plafond else 0)), c['numero']))
        choix = [c['numero'] for c in ordre[:5]]
        sorties.append({
            'moteur': nom, 'gagnant_espere': choix[0],
            'meilleur_place': choix[1], 'ordre_espere': choix,
            'qualification': 'EXPERIMENTAL',
            'validation': 'DONNEES_PARTIELLES', 'pari_retenu': None,
        })
    return sorties


def horodatage(ms):
    return datetime.fromtimestamp(int(ms) / 1000, PARIS)


def empreinte(contenu):
    return hashlib.sha256(json.dumps(contenu, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def collecter(date):
    code = datetime.strptime(date, '%Y-%m-%d').strftime('%d%m%Y')
    programme = api(f'/programme/{code}?specialisation=INTERNET')
    courses = extraire_courses(programme, date)
    figes = lire('figes.json', {})
    pv = lire('pv.json', {})
    if not isinstance(figes, dict) or not isinstance(pv, dict):
        raise ValueError('Fichiers PV/FIGES invalides')
    donnees = []
    erreurs = 0
    for course in courses:
        cid = identite(course)
        try:
            reponse = api(f"/programme/{code}/R{course['reunion']}/C{course['course']}/participants?specialisation=INTERNET")
            chevaux = extraire_partants(reponse)
            course['partants'] = chevaux
            course['nombre_partants'] = sum(not c['non_partant'] for c in chevaux)
            depart = horodatage(course['depart_ms'])
            instant = maintenant()
            restant = (depart - instant).total_seconds()
            predictions = moteurs(chevaux) if restant > 0 else []
            if restant > 0 and predictions and cid not in figes:
                pv[cid] = {'course': cid, 'cree_a': instant.isoformat(),
                           'depart': depart.isoformat(), 'moteurs': predictions}
            if 0 < restant <= 1200 and predictions and cid not in figes:
                contenu = {'course': cid, 'fige_a': instant.isoformat(),
                           'depart': depart.isoformat(), 'moteurs': predictions}
                contenu['sha256'] = empreinte(contenu)
                figes[cid] = contenu
            course['moteurs'] = (figes[cid]['moteurs'] if cid in figes else predictions)
            course['statut'] = ('FIGE' if cid in figes else
                               'PV' if predictions else 'SANS_PRONOSTIC')
        except Exception as exc:
            erreurs += 1
            course['statut'] = 'ERREUR_SOURCE'
            course['erreur'] = str(exc)
            course['moteurs'] = []
        donnees.append(course)
    sauver('pv.json', pv)
    sauver('figes.json', figes)
    sauver('courses.json', {'date': date, 'actualise': maintenant().isoformat(),
                            'courses': donnees})
    return len(donnees), erreurs


def extraire_arrivee(reponse):
    if not isinstance(reponse, dict):
        return []
    brut = reponse.get('ordreArrivee')
    if isinstance(brut, list) and brut and isinstance(brut[0], list):
        brut = brut[0]
    if not isinstance(brut, list):
        return []
    ordre = [entier(x) for x in brut]
    return ordre if len(ordre) >= 1 and all(x and x > 0 for x in ordre) else []


def auditer(date):
    code = datetime.strptime(date, '%Y-%m-%d').strftime('%d%m%Y')
    figes = lire('figes.json', {})
    audits = lire('audits.json', {})
    if not isinstance(figes, dict) or not isinstance(audits, dict):
        raise ValueError('Fichiers audits/FIGES invalides')
    for cid, fige in figes.items():
        if not cid.startswith(date + '-') or cid in audits:
            continue
        try:
            correspondance = re.fullmatch(r'\d{4}-\d{2}-\d{2}-R(\d+)-C(\d+)', cid)
            if not correspondance:
                continue
            rn, cn = correspondance.groups()
            resultat = api(f'/programme/{code}/R{rn}/C{cn}/arrivee-definitive?specialisation=INTERNET')
            ordre = extraire_arrivee(resultat)
            if not ordre:
                continue
            bilans = []
            for m in fige['moteurs']:
                choix = m['ordre_espere']
                bilans.append({'moteur': m['moteur'], 'selection': choix,
                               'gagnant_correct': choix[0] == ordre[0],
                               'chevaux_top5': len(set(choix) & set(ordre[:5]))})
            audits[cid] = {'arrivee': ordre, 'audite_a': maintenant().isoformat(),
                           'source': 'PMU', 'fige_sha256': fige['sha256'],
                           'bilans': bilans}
        except (KeyError, ValueError, urllib.error.URLError) as exc:
            print(f'Audit indisponible {cid}: {exc}')
    sauver('audits.json', audits)


def main():
    date = maintenant().date().isoformat()
    rapport = {'execution': maintenant().isoformat(), 'date': date,
               'statut': 'ERREUR', 'courses': 0, 'erreurs_courses': 0}
    try:
        total, erreurs = collecter(date)
        rapport['courses'] = total
        rapport['erreurs_courses'] = erreurs
        rapport['statut'] = ('AUCUNE_COURSE' if total == 0 else
                             'PARTIEL' if erreurs else 'OK')
        auditer(date)
        auditer((maintenant() - timedelta(days=1)).date().isoformat())
    except Exception as exc:
        rapport['erreur'] = str(exc)
        print(f'ERREUR: {exc}')
    finally:
        sauver('rapport.json', rapport)
        print(json.dumps(rapport, ensure_ascii=False))
    if rapport['statut'] == 'ERREUR':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
