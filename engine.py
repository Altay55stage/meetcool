"""meet'cool — transparent and testable optimization engine.
Exact optimization on a finite candidate set; travel-time approximation explicitly labelled.
"""
from math import radians,sin,cos,asin,sqrt,inf,isfinite
from datetime import datetime, timedelta
from heapq import heappush, heappop

SPEED_KMH = {"car": 48, "bike": 16, "walk": 4.5, "transit": 25}
DETOUR = {"car": 1.32, "bike": 1.22, "walk": 1.18, "transit": 1.5}

def haversine(a, b):
    lat1,lon1,lat2,lon2 = map(radians,(a['lat'],a['lng'],b['lat'],b['lng']))
    dlat=lat2-lat1; dlon=lon2-lon1
    return 6371*2*asin(sqrt(sin(dlat/2)**2+cos(lat1)*cos(lat2)*sin(dlon/2)**2))

def approx_minutes(a,b,mode='car'):
    if mode not in SPEED_KMH: mode='car'
    return round(60*haversine(a,b)*DETOUR[mode]/SPEED_KMH[mode],1)

def dijkstra(graph, source):
    """Adjacency dict {vertex: [(neighbor, positive_weight), ...]} — O((V+E)logV)."""
    dist={source:0}; previous={}; heap=[(0,source)]
    while heap:
        d,u=heappop(heap)
        if d>dist[u]: continue
        for v,w in graph.get(u,[]):
            if w<0: raise ValueError('Negative edges are not allowed')
            candidate=d+w
            if candidate<dist.get(v,inf):
                dist[v]=candidate;previous[v]=u;heappush(heap,(candidate,v))
    return dist,previous

def reconstruct_path(previous, source, destination):
    if source==destination:return [source]
    if destination not in previous:return []
    path=[destination]
    while path[-1]!=source:
        path.append(previous[path[-1]])
    return path[::-1]

def floyd_warshall(vertices, edges):
    d={u:{v:(0 if u==v else inf) for v in vertices} for u in vertices}
    for u,v,w in edges: d[u][v]=min(d[u][v],w)
    for k in vertices:
        for i in vertices:
            for j in vertices:
                d[i][j]=min(d[i][j],d[i][k]+d[k][j])
    return d

def _minute(ts):
    if not ts: return 0
    try: return datetime.fromisoformat(ts).timestamp()/60
    except (TypeError,ValueError):return 0

def optimize(participants, venues, objective='earliest', start_at=None, duration=60, travel_matrix=None):
    """Exhaustive and provably optimal among *supplied candidate venues*.
    If travel_matrix exists, each row holds minutes for one participant per venue.
    Arrival-based score assumes departure is available_at or meeting start.
    """
    if not participants or not venues: return {'ranking':[], 'matrix':[], 'error':'Participants and venues required'}
    if objective not in ('earliest','fair','total','minimax'):objective='earliest'
    ref=_minute(start_at)
    available=[max(ref,_minute(p.get('available_at'))) for p in participants]
    matrix=travel_matrix or [[approx_minutes(p,v,p.get('mode','car')) for v in venues] for p in participants]
    rows=[]
    for j,v in enumerate(venues):
        times=[float(matrix[i][j]) for i in range(len(participants))]
        if any(not isfinite(t) or t<0 for t in times):raise ValueError('Travel times must be finite and nonnegative')
        arrival=max(available[i]+times[i] for i in range(len(participants)))
        fairness=max(times)-min(times)
        total=sum(times); maximum=max(times)
        # Must finish within optional participant's available_until window.
        feasible=all(not p.get('available_until') or arrival+duration <= _minute(p['available_until']) for p in participants)
        rows.append({'id':v['id'],'name':v['name'],'lat':v['lat'],'lng':v['lng'],'description':v.get('description',''), 'times':times,'total':round(total,1),'max':round(maximum,1),'spread':round(fairness,1),'arrival_epoch_min':arrival,'feasible':feasible})
    sortkeys={'earliest':lambda r:(r['arrival_epoch_min'],r['total'],r['spread']), 'fair':lambda r:(r['spread'],r['total'],r['arrival_epoch_min']), 'total':lambda r:(r['total'],r['max']), 'minimax':lambda r:(r['max'],r['total'])}
    rows.sort(key=lambda r:(not r['feasible'],*sortkeys[objective](r)))
    for rank,r in enumerate(rows):r['rank']=rank+1
    return {'ranking':rows,'matrix':matrix,'optimality':'Exact on enumerated candidate venues','routing':'estimated' if travel_matrix is None else 'provided','objective':objective,'feasible':any(r['feasible'] for r in rows)}
