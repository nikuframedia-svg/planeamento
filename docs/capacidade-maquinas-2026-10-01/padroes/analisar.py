"""Passo 2: porque é que cada peça vai para punção ou broca, e qual Rapid. Só leitura dos ficheiros exportados.
uv run --with pandas --with scikit-learn python docs/capacidade-maquinas-2026-10-01/padroes/analisar.py"""
import json, re
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.tree import DecisionTreeClassifier, export_text

HERE = Path(__file__).resolve().parent
d = pd.read_json(HERE / 'mtg3.jsonl', lines=True)
num = lambda s: pd.to_numeric(s, errors='coerce')
d['Q'], d['L'], d['made'], d['mprod'] = num(d['QTD']), num(d['Comp.']), num(d['Maq.']), num(d['m prod.'])
d['op1'] = d['1ª Oper.'].astype(str).str.replace('.0', '', regex=False).str.strip()
d['mach'] = d['Máquina Corte'].fillna('').astype(str).str.strip()
d['fam'] = d.mach.map(lambda m: 'Rapid' if 'Rapid' in m else 'XP' if 'XP' in m else 'Peddi' if 'Peddi' in m else 'Sem' if not m else 'Outra')
def dims(p):
    m = re.search(r'L\s*(\d+(?:[.,]\d+)?)\s*X\s*(\d+(?:[.,]\d+)?)\s*X\s*(\d+(?:[.,]\d+)?)', str(p).upper())
    return [float(x.replace(',', '.')) for x in m.groups()] if m else [np.nan] * 3
D = np.array([dims(p) for p in d['Tipo de perfil'].fillna(d['Des. Material'])])
d['a'], d['t'] = np.maximum(D[:, 0], D[:, 1]), D[:, 2]
out = {}
e = d[(d.mprod > 0) & d.fam.isin(['Rapid', 'XP', 'Peddi'])].dropna(subset=['Q', 't', 'a', 'L']).copy()
out['linhas_executadas'] = len(e)
out['codigo_vs_familia_linhas'] = pd.crosstab(e.op1, e.fam).to_dict()
for name, bins, col in (('quantidade', [0, 2, 5, 10, 20, 50, 100, 1e6], 'Q'), ('espessura', [0, 4, 5, 6, 8, 10, 12, 16, 30], 't'),
                        ('aba', [0, 50, 60, 70, 80, 100, 120, 150, 300], 'a'), ('comprimento', [0, 1000, 2000, 4000, 6000, 13000], 'L')):
    t = pd.crosstab(pd.cut(e[col], bins), e.fam, normalize='index').round(3)
    t.index = t.index.astype(str); out['familia_por_' + name] = t.to_dict(orient='index')
    t.to_csv(HERE / f'familia-por-{name}.csv')
e['metres'] = e.Q * e.L / 1000
G = e.groupby([e.OF.astype(str), 'Tipo de perfil']).agg(meanQ=('Q', 'mean'), maxQ=('Q', 'max'), pieces=('Q', 'sum'), lines=('Q', 'size'),
    t=('t', 'first'), a=('a', 'first'), meanL=('L', 'mean'), maxL=('L', 'max'), metres=('metres', 'sum'),
    op119=('op1', lambda s: (s == '119').mean()), fam=('fam', lambda s: s.mode()[0]), families=('fam', 'nunique')).reset_index()
G['drill'] = (G.fam == 'Rapid').astype(int)
out['grupos_OF_perfil'] = len(G); out['grupos_numa_so_familia'] = round((G.families == 1).mean(), 4)
acc = lambda pred: round(float(((pred.astype(int) == G.drill) * G.metres).sum() / G.metres.sum()), 4)
out['acerto_por_codigo_119'] = acc(G.op119 > .5)
out['acerto_regra_series'] = {k: acc((G.meanQ < k) | (G.t > 9.5) | (G.a > 120)) for k in (4, 5, 6, 8, 10, 12)}
cols = ['meanQ', 'maxQ', 'pieces', 'lines', 't', 'a', 'meanL', 'maxL']
y, g = G.drill.values, G.OF.values
hit = tot = 0
for tr, te in GroupKFold(5).split(G, y, g):
    m = DecisionTreeClassifier(max_depth=3, min_samples_leaf=40, random_state=0).fit(G.iloc[tr][cols], y[tr])
    w = G.iloc[te].metres.values; hit += ((m.predict(G.iloc[te][cols]) == y[te]) * w).sum(); tot += w.sum()
out['arvore_validada_por_OF'] = round(hit / tot, 4)
(HERE / 'arvore.txt').write_text(export_text(DecisionTreeClassifier(max_depth=3, min_samples_leaf=40, random_state=0).fit(G[cols], y), feature_names=cols, show_weights=True))
r = e[e.fam == 'Rapid'].copy()
t = pd.crosstab(pd.cut(r.a, [0, 59, 80, 100, 120, 150, 300]), r.mach, values=r.mprod, aggfunc='sum', normalize='index').round(3)
t.index = t.index.astype(str); out['rapid_por_aba'] = t.to_dict(orient='index'); t.to_csv(HERE / 'rapid-por-aba.csv')
out['rapid_mesmo_OF_perfil'] = round(float((r.groupby([r.OF.astype(str), 'Tipo de perfil']).mach.nunique() == 1).mean()), 4)
out['rapid_OF_inteira'] = round(float((r.groupby(r.OF.astype(str)).mach.nunique() == 1).mean()), 4)
u = d[(d.mach == '') & (d.Q - d.made.fillna(0) > 0)].copy(); u['m'] = (u.Q - u.made.fillna(0)) * u.L / 1000
U = u.groupby([u.OF.astype(str), 'Tipo de perfil']).agg(meanQ=('Q', 'mean'), t=('t', 'first'), a=('a', 'first'), m=('m', 'sum')).reset_index()
U['drill'] = (U.meanQ < 8) | (U.t > 9.5) | (U.a > 120)
out['sem_maquina_km'] = {'total': round(U.m.sum() / 1000, 1), 'broca_pela_regra': round(U[U.drill].m.sum() / 1000, 1),
                        'puncao_pela_regra': round(U[~U.drill].m.sum() / 1000, 1),
                        'por_codigo_119': round(u[u.op1 == '119'].m.sum() / 1000, 1)}
(HERE / 'resultado.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
print(json.dumps({k: out[k] for k in ('linhas_executadas', 'grupos_numa_so_familia', 'acerto_por_codigo_119', 'acerto_regra_series', 'arvore_validada_por_OF', 'rapid_mesmo_OF_perfil', 'sem_maquina_km')}, ensure_ascii=False, indent=1))
