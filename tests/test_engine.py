from engine import haversine,dijkstra,reconstruct_path,floyd_warshall,optimize

def test_dijkstra():
    g={'A':[('B',10),('C',1)],'C':[('B',2)],'B':[]}
    d,p=dijkstra(g,'A')
    assert d['B']==3 and reconstruct_path(p,'A','B')==['A','C','B']

def test_floyd():
    d=floyd_warshall(['A','B','C'],[('A','B',3),('B','C',2),('A','C',10)])
    assert d['A']['C']==5

def test_optimize_objectives():
    ps=[{'lat':0,'lng':0} for _ in range(3)]
    vs=[{'id':'a','name':'a','lat':0,'lng':0},{'id':'b','name':'b','lat':0,'lng':0}]
    matrix=[[10,20],[10,20],[30,20]]
    assert optimize(ps,vs,'fair',travel_matrix=matrix)['ranking'][0]['id']=='b'
    assert optimize(ps,vs,'total',travel_matrix=matrix)['ranking'][0]['id']=='a'
    assert optimize(ps,vs,'minimax',travel_matrix=matrix)['ranking'][0]['id']=='b'

def test_haversine_same():
    p={'lat':47.5,'lng':6.8}
    assert haversine(p,p)==0
