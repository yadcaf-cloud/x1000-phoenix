#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — coordination consultative M1–M5, lecture seule.

python autonomie_complete_m1_m5.py --self-test
python autonomie_complete_m1_m5.py
python autonomie_complete_m1_m5.py --course 2026-10-30-R1-C1

Aucune écriture, aucune prédiction nouvelle, aucune validation et aucun FIGÉ créé.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
PARIS = ZoneInfo('Europe/Paris')
ENGINES = ('M1', 'M2', 'M3', 'M4', 'M5')
COURSE_FILES = ('publication_courses.json', 'collecte.json', 'courses_verifiees.json', 'courses.json', 'courses_pmu.json')
ANALYSIS_FILES = ('publication_analyses.json', 'publication_pronostics.json', 'analyses.json', 'pronostics.json')
RESULT_FILES = ('publication_resultats.json', 'resultats_officiels.json', 'resultats.json')
FIGE_FILES = ('publication_figes.json', 'figes.json')
SPORT = ('musique', 'gains', 'age', 'sexe', 'entraineur')
OPTIONAL = ('distance', 'terrain', 'historique_distance', 'historique_terrain', 'performances_detaillees', 'niveau_opposition')


def value(obj, *keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        v = obj.get(key)
        if v is not None and v != '' and v != [] and v != {}:
            return v
    return None


def number(v):
    if type(v) is int and v > 0:
        return v
    if isinstance(v, str) and re.fullmatch(r'0*[1-9][0-9]*', v.strip()):
        return int(v.strip())
    return None


def timestamp(v):
    if not isinstance(v, str):
        return None
    try:
        t = dt.datetime.fromisoformat(v.strip().replace('Z', '+00:00'))
        return t.astimezone(PARIS) if t.tzinfo is not None and t.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def identity(obj):
    v = value(obj, 'course_id', 'id_course', 'id', 'identifiant')
    return str(v).strip() if v is not None and not isinstance(v, bool) else ''


def read_collection(names, keys):
    notes = []
    for name in names:
        p = DATA / name
        if not p.is_file():
            continue
        try:
            with p.open(encoding='utf-8-sig') as f:
                raw = json.load(f)
            if isinstance(raw, list) and raw:
                return raw, name, notes
            if isinstance(raw, dict):
                for container in (raw, raw.get('data')):
                    if isinstance(container, dict):
                        for key in keys:
                            rows = container.get(key)
                            if isinstance(rows, list) and rows:
                                return rows, name, notes
            notes.append(name + ': collection vide ou incompatible')
        except (OSError, ValueError, UnicodeError) as exc:
            notes.append(f'{name}: {exc}')
    return [], None, notes


def index_unique(rows):
    groups = defaultdict(list)
    for row in rows:
        if isinstance(row, dict) and identity(row):
            groups[identity(row)].append(row)
    return {k: v[0] for k, v in groups.items() if len(v) == 1}, sorted(k for k, v in groups.items() if len(v) > 1)


def engines_by_course(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = identity(row)
        block = row.get('moteurs')
        if isinstance(block, list):
            entries = block
        elif isinstance(block, dict):
            entries = [{**item, 'moteur': key} for key, item in block.items() if isinstance(item, dict)]
        else:
            entries = [row]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = identity(entry) or cid
            engine = str(value(entry, 'moteur', 'nom_moteur') or '').upper().strip()
            if eid and engine in ENGINES:
                grouped[eid][engine].append(entry)
    selected, conflicts, repeated = defaultdict(dict), defaultdict(list), defaultdict(list)
    for cid, engines in grouped.items():
        for name, versions in engines.items():
            signatures = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in versions}
            if len(signatures) > 1:
                conflicts[cid].append(name)
            else:
                selected[cid][name] = versions[0]
                if len(versions) > 1:
                    repeated[cid].append(name)
    return selected, conflicts, repeated


def nonrunner(h):
    status = str(value(h, 'statut', 'status') or '').upper().replace('-', '_').replace(' ', '_')
    return h.get('non_partant') is True or h.get('nonPartant') is True or status in ('NP', 'NON_PARTANT', 'NONPARTANT', 'FORFAIT')


def horse_audit(course):
    horses = value(course, 'partants', 'participants', 'chevaux')
    horses = horses if isinstance(horses, list) else []
    known, np_cards, detail, problems = set(), set(), [], []
    for h in horses:
        if not isinstance(h, dict):
            problems.append('Fiche cheval invalide')
            continue
        n = number(value(h, 'numero', 'numPmu', 'numeroPmu', 'num'))
        if n is None or n in known:
            problems.append('Numéro absent, invalide ou répété')
            continue
        known.add(n)
        if nonrunner(h):
            np_cards.add(n)
        missing = [k for k in SPORT if value(h, k) is None]
        if value(h, 'jockey', 'driver') is None:
            missing.append('jockey_ou_driver')
        detail.append({'numero': n, 'nom': value(h, 'nom', 'nomCheval'),
                       'champs_manquants': missing,
                       'champs_complementaires_disponibles': [k for k in OPTIONAL if value(h, k) is not None]})
    raw_np = course.get('non_partants')
    np_list = set()
    if raw_np is not None:
        if not isinstance(raw_np, list):
            problems.append('Liste de non-partants invalide')
        else:
            for item in raw_np:
                n = number(value(item, 'numero', 'numPmu', 'num') if isinstance(item, dict) else item)
                if n is None:
                    problems.append('Numéro de non-partant invalide')
                else:
                    np_list.add(n)
            if np_list != np_cards:
                problems.append('Incohérence non-partants : liste et fiches')
    excluded = np_cards | np_list
    if excluded - known:
        problems.append('Non-partant absent des fiches')
    return {'numeros': sorted(known), 'non_partants': sorted(excluded),
            'fiches': detail, 'anomalies': problems}


def ordered(e):
    raw = value(e, 'ordre_espere', 'ordre_arrivee_espere', 'ordre')
    if not isinstance(raw, list) or len(raw) != 5:
        return None, 'Combinaison ordonnée de cinq numéros absente'
    nums = [number(x) for x in raw]
    if None in nums or len(set(nums)) != 5:
        return None, 'Numéros invalides ou répétés dans la combinaison'
    return nums, None


def prestart(course, prediction):
    issues = []
    if course.get('localisation_france_verifiee') is not True:
        issues.append('France non vérifiée')
    if course.get('depart_verifie') is not True:
        issues.append('Départ officiel non vérifié')
    depart = timestamp(value(course, 'depart', 'heure_depart'))
    calculated = timestamp(value(prediction, 'analyse_a', 'heure_analyse', 'horodatage'))
    published = timestamp(value(prediction, 'publie_a', 'publication_a', 'date_publication'))
    if depart is None:
        issues.append('Heure de départ absente ou sans fuseau')
    if calculated is None:
        issues.append('Heure de calcul non prouvée')
    if published is None:
        issues.append('Heure de publication non prouvée')
    if depart and calculated and calculated >= depart:
        issues.append('Calcul non antérieur au départ')
    if depart and published and published >= depart:
        issues.append('Publication non antérieure au départ')
    if calculated and published and published < calculated:
        issues.append('Publication antérieure au calcul')
    return issues


def audit_prediction(course, sport, engine, prediction):
    issues = list(sport['anomalies'])
    known, excluded = set(sport['numeros']), set(sport['non_partants'])
    combo, error = ordered(prediction)
    winner = number(prediction.get('gagnant_espere'))
    placed = number(prediction.get('meilleur_place'))
    if error:
        issues.append(error)
    if winner is None:
        issues.append('Gagnant espéré absent ou invalide')
    if placed is None:
        issues.append('Meilleur placé espéré absent ou invalide')
    if not known:
        issues.append('Partants non vérifiables')
    for label, n in [('gagnant', winner), ('placé', placed)] + ([(f'position {i}', n) for i, n in enumerate(combo, 1)] if combo else []):
        if n is None:
            continue
        if n in excluded:
            issues.append(f'{label} : non-partant {n}')
        elif n not in known:
            issues.append(f'{label} : numéro inconnu {n}')
    if combo and winner is not None and combo[0] != winner:
        issues.append('Gagnant distinct de la position 1')
    # Le meilleur placé peut être une décision distincte de la position 2.
    issues += prestart(course, prediction)
    if value(course, 'source') is None:
        issues.append('Source de la course absente')
    return {'moteur': engine, 'gagnant_brut': prediction.get('gagnant_espere'),
            'meilleur_place_brut': prediction.get('meilleur_place'),
            'combinaison_brute': value(prediction, 'ordre_espere', 'ordre_arrivee_espere', 'ordre'),
            'combinaison_interpretable': combo, 'anomalies': issues,
            'statut': 'CONTROLES_CONSULTATIFS_SANS_ANOMALIE' if not issues else 'A_CONTROLER',
            'validation_officielle': False, 'fige_cree': False}


def final_arrival(result):
    """N'évalue que les résultats explicitement définitifs et sourcés."""
    status = str(value(result, 'statut', 'status') or '').upper().strip()
    if status not in ('DEFINITIF', 'DÉFINITIF', 'OFFICIEL_DEFINITIF', 'OFFICIEL_DÉFINITIF'):
        return None, 'Résultat non explicitement définitif'
    if not value(result, 'source', 'source_officielle') or not timestamp(value(result, 'publie_a', 'publication_a', 'date_publication')):
        return None, 'Source ou publication officielle non vérifiable'
    raw = value(result, 'arrivee_officielle', 'arrivee', 'classement')
    if not isinstance(raw, list) or len(raw) < 5:
        return None, 'Arrivée officielle insuffisante'
    nums = [number(value(x, 'numero', 'numPmu') if isinstance(x, dict) else x) for x in raw]
    if None in nums or len(set(nums)) != len(nums):
        return None, 'Arrivée officielle invalide'
    return nums, None


def audit_result(prediction, result):
    arrival, reason = final_arrival(result)
    if reason:
        return {'evaluable': False, 'raison': reason}
    combo, problem = ordered(prediction)
    winner = number(prediction.get('gagnant_espere'))
    placed = number(prediction.get('meilleur_place'))
    if problem or winner is None or placed is None:
        return {'evaluable': False, 'raison': 'Prédiction incomplète'}
    return {'evaluable': True, 'gagnant': winner == arrival[0],
            'place_top3': placed in arrival[:3],
            'chevaux_top5': len(set(combo) & set(arrival[:5])),
            'cinq_sans_ordre': set(combo) == set(arrival[:5]),
            'cinq_dans_ordre': combo == arrival[:5]}


def stats_summary(events):
    summary = {}
    for name in ENGINES:
        rows = [r for engine, r in events if engine == name and r['evaluable']]
        n = len(rows)
        wins = {key: sum(int(r[key]) for r in rows) for key in ('gagnant', 'place_top3', 'cinq_sans_ordre', 'cinq_dans_ordre')}
        summary[name] = {'courses_evaluees': n, 'reussites': wins,
                         'taux_pourcent': {k: round(v * 100 / n, 2) if n else None for k, v in wins.items()},
                         'nombre_moyen_top5': round(sum(r['chevaux_top5'] for r in rows) / n, 2) if n else None}
    return summary


def figes_inventory(rows):
    """Inventaire uniquement ; aucun hash n'est présenté comme preuve d'authenticité."""
    entries = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entries.append({'course_id': identity(row), 'moteur': value(row, 'moteur'),
                        'empreinte_declaree': value(row, 'sha256', 'fige_sha256'),
                        'verification_authenticite': 'NON_EFFECTUEE_PAR_CE_MODULE'})
    return entries


def self_test():
    assert number('07') == 7 and number(True) is None
    assert ordered({'ordre_espere': [1, 2, 3, 4, 5]})[0] == [1, 2, 3, 4, 5]
    assert ordered({'ordre_espere': [1, 1, 3, 4, 5]})[0] is None
    course = {'id': 'TEST', 'localisation_france_verifiee': True, 'depart_verifie': True,
              'depart': '2026-10-30T15:00:00+01:00', 'source': 'https://example.org',
              'partants': [{'numero': n, 'nom': str(n)} for n in range(1, 7)], 'non_partants': []}
    prediction = {'moteur': 'M1', 'gagnant_espere': 1, 'meilleur_place': 3,
                  'ordre_espere': [1, 2, 3, 4, 5], 'analyse_a': '2026-10-30T14:00:00+01:00',
                  'publie_a': '2026-10-30T14:01:00+01:00'}
    assert audit_prediction(course, horse_audit(course), 'M1', prediction)['anomalies'] == []
    assert 'Publication non antérieure au départ' in prestart(course, {**prediction, 'publie_a': '2026-10-30T16:00:00+01:00'})
    assert horse_audit({**course, 'non_partants': [2]})['anomalies']
    result = {'id': 'TEST', 'statut': 'DEFINITIF', 'source': 'https://example.org',
              'publie_a': '2026-10-30T16:00:00+01:00', 'arrivee_officielle': [1, 2, 3, 4, 5]}
    assert audit_result(prediction, result)['cinq_dans_ordre'] is True
    assert audit_result(prediction, {**result, 'statut': 'PROVISOIRE'})['evaluable'] is False
    rows = [{'course_id': 'TEST', 'moteurs': [prediction, dict(prediction)]}]
    groups, conflicts, repeats = engines_by_course(rows)
    assert not conflicts['TEST'] and repeats['TEST'] == ['M1']
    rows[0]['moteurs'][1]['gagnant_espere'] = 4
    groups, conflicts, repeats = engines_by_course(rows)
    assert conflicts['TEST'] == ['M1'] and 'M1' not in groups['TEST']
    print('SELF-TEST OK — module consultatif, aucun fichier modifié')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--course')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    courses, cs, cw = read_collection(COURSE_FILES, ('courses', 'courses_verifiees'))
    analyses, ans, aw = read_collection(ANALYSIS_FILES, ('analyses', 'pronostics'))
    results, rs, rw = read_collection(RESULT_FILES, ('resultats', 'resultats_officiels', 'courses'))
    figes, fs, fw = read_collection(FIGE_FILES, ('figes', 'figés'))
    course_map, duplicate_courses = index_unique(courses)
    result_map, duplicate_results = index_unique(results)
    grouped, conflicts, repeats = engines_by_course(analyses)
    ids = [args.course] if args.course else sorted(set(course_map) | set(grouped) | set(conflicts))
    events, course_reports = [], []
    for cid in ids:
        if cid in duplicate_courses:
            course_reports.append({'course_id': cid, 'statut': 'COURSE_DUPLIQUEE_NON_ARBITREE'})
            continue
        course = course_map.get(cid)
        if course is None:
            course_reports.append({'course_id': cid, 'statut': 'COURSE_ABSENTE'})
            continue
        sport = horse_audit(course)
        report = {'course_id': cid, 'donnees_sportives': sport, 'moteurs': {},
                  'analyses_contradictoires': conflicts[cid], 'analyses_identiques_repetees': repeats[cid]}
        for name in ENGINES:
            if name in conflicts[cid]:
                report['moteurs'][name] = {'statut': 'AMBIGU', 'raison': 'Décisions contradictoires'}
                continue
            prediction = grouped[cid].get(name)
            if prediction is None:
                report['moteurs'][name] = {'statut': 'ABSENT'}
                continue
            check = audit_prediction(course, sport, name, prediction)
            if cid in duplicate_results:
                check['audit_resultat'] = {'evaluable': False, 'raison': 'Résultats contradictoires ou dupliqués'}
            elif cid in result_map:
                # Seules les décisions suffisamment traçables sont évaluées.
                if check['anomalies']:
                    check['audit_resultat'] = {'evaluable': False, 'raison': 'Contrôles préalables non satisfaits'}
                else:
                    check['audit_resultat'] = audit_result(prediction, result_map[cid])
                    events.append((name, check['audit_resultat']))
            report['moteurs'][name] = check
        course_reports.append(report)
    output = {'systeme': 'X1000 PHOENIX', 'version': '1.0-LECTURE-SEULE',
              'heure_paris': dt.datetime.now(PARIS).isoformat(),
              'aucune_ecriture': True, 'aucun_pronostic_recalcule': True,
              'aucun_fige_cree': True, 'aucune_validation_officielle': True,
              'sources': {'courses': cs, 'analyses': ans, 'resultats': rs, 'figes': fs},
              'avertissements': cw + aw + rw + fw,
              'courses': course_reports, 'statistiques': stats_summary(events),
              'inventaire_figes': figes_inventory(figes),
              'note': 'Audit descriptif. Aucun apprentissage ou déploiement automatique.'}
    print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
