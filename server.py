"""FastAPI web app with local SQLite or shared Appwrite/Supabase storage; launch: uvicorn server:app --reload."""
import secrets
import os
import re
from urllib.parse import urlencode
from typing import Literal
from math import isfinite, radians, degrees, sin, cos, atan2, sqrt
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from storage import MeetingStore, MeetingNotFound, StorageUnavailable
from geo import router as geo_router, road_matrix
from pydantic import BaseModel, Field, field_validator
from notifications import Mailer, google_maps_urls
from engine import optimize, dijkstra, reconstruct_path, floyd_warshall

ROOT=Path(__file__).parent
app=FastAPI(title="meet'cool API", version='2.0.0')
store=MeetingStore()
mailer=Mailer()
PUBLIC_APP_URL=os.environ.get("PUBLIC_APP_URL", "https://meetcool-three.vercel.app").rstrip("/")
app.include_router(geo_router)

@app.exception_handler(StorageUnavailable)
def storage_error(request, exc):
    return JSONResponse(status_code=503,content={'detail':str(exc)})

@app.exception_handler(MeetingNotFound)
def missing_meeting(request, exc):
    return JSONResponse(status_code=404,content={'detail':'Réunion introuvable.'})

@app.get('/api/config')
def configuration():
    return {**store.config(),'map':'OpenStreetMap','traffic_live':False,'version':'2.0.0','email':mailer.config()}

DEMO_VENUES=[
 {'id':'v1','name':'Café du Théâtre · Montbéliard','lat':47.5107,'lng':6.7985,'description':'Centre de Montbéliard · lieu indicatif'},
 {'id':'v2','name':'Place d’Armes · Belfort','lat':47.6376,'lng':6.8629,'description':'Centre de Belfort · espace public'},
 {'id':'v3','name':'Place de la Révolution · Besançon','lat':47.2404,'lng':6.0228,'description':'Centre de Besançon · espace public'},
 {'id':'v4','name':'Gare TGV Belfort–Montbéliard','lat':47.5869,'lng':6.8977,'description':'Point d’accès multimodal · horaires à vérifier'},
 {'id':'v5','name':'Centre-ville · Héricourt','lat':47.5762,'lng':6.7601,'description':'Centre de Héricourt · lieu indicatif'},
 {'id':'v6','name':'Centre-ville · L’Isle-sur-le-Doubs','lat':47.4471,'lng':6.581,'description':'Point de rencontre indicatif'}]
DEMO_PARTICIPANTS=[
 {'id':'a','name':'Toi','lat':47.509,'lng':6.798,'mode':'car','status':'ready'},
 {'id':'b','name':'Camille','lat':47.638,'lng':6.863,'mode':'car','status':'ready'},
 {'id':'c','name':'Alex','lat':47.238,'lng':6.025,'mode':'car','status':'ready'}]

class EmailFields(BaseModel):
    @field_validator('organizer_email', 'email', check_fields=False)
    @classmethod
    def valid_email(cls, value):
        if value is None or not value.strip():return None
        value=value.strip()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
            raise ValueError('Adresse e-mail invalide.')
        return value

class CreateMeeting(EmailFields):
    organizer_email:str|None=Field(default=None,max_length=254)
    name:str=Field(min_length=2,max_length=150)
    date:str|None=None
    duration:int=Field(default=60,ge=15,le=480)
    objective:Literal['earliest','fair','total','minimax']='earliest'
    description:str=Field(default='',max_length=2000)
    venues:list[dict]|None=Field(default=None,max_length=200)

class Guest(EmailFields):
    email:str|None=Field(default=None,max_length=254)
    name:str=Field(min_length=1,max_length=80)
    lat:float=Field(ge=-90,le=90)
    lng:float=Field(ge=-180,le=180)
    mode:Literal['car','bike','walk','transit']='car'
    available_at:str|None=None
    available_until:str|None=None
    location_source:Literal['current','planned']='planned'
    location_label:str=Field(default='',max_length=300)

class MeetingUpdate(BaseModel):
    objective:Literal['earliest','fair','total','minimax']|None=None
    venues:list[dict]|None=Field(default=None,min_length=1,max_length=200)
    status:Literal['collecting','confirmed','cancelled']|None=None
    chosen_venue:str|None=None

class Status(BaseModel):
    state:str

class OptimizeRequest(BaseModel):
    participants:list[dict]=Field(min_length=1)
    venues:list[dict]=Field(min_length=1,max_length=200)
    objective:Literal['earliest','fair','total','minimax']='earliest'
    start_at:str|None=None
    duration:int=Field(default=60,ge=15,le=480)
    travel_matrix:list[list[float]]|None=None

@app.get('/')
def home():return FileResponse(ROOT/'static'/'index.html')
@app.get('/app.js')
def script():return FileResponse(ROOT/'static'/'app.js',media_type='application/javascript')
@app.get('/styles.css')
def css():return FileResponse(ROOT/'static'/'styles.css',media_type='text/css')
@app.get('/landing.css')
def landing_css():return FileResponse(ROOT/'static'/'landing.css',media_type='text/css')
@app.get('/i18n.js')
def language_script():return FileResponse(ROOT/'static'/'i18n.js',media_type='application/javascript')
@app.get('/translations.js')
def translations_script():return FileResponse(ROOT/'static'/'translations.js',media_type='application/javascript')
@app.get('/motion.js')
def motion_script():return FileResponse(ROOT/'static'/'motion.js',media_type='application/javascript')
@app.get('/api/health')
def health():return {'ok':True,'product':"meet'cool"}
@app.get('/api/demo')
def demo():return {'participants':DEMO_PARTICIPANTS,'venues':DEMO_VENUES}
def validate_points(points):
    for point in points:
        try:
            lat=float(point['lat']);lng=float(point['lng'])
            valid=isfinite(lat) and isfinite(lng) and -90<=lat<=90 and -180<=lng<=180
            valid=valid and bool(point.get('id')) and bool(point.get('name'))
        except (KeyError,ValueError,TypeError):valid=False
        if not valid:raise HTTPException(422,'Coordonnées, identifiant et nom valides requis.')


def optimized(participants,venues,objective,start_at=None,duration=60,travel_matrix=None):
    validate_points(participants);validate_points(venues)
    matrix=travel_matrix if travel_matrix is not None else road_matrix(participants,venues)
    try:
        result=optimize(participants,venues,objective,start_at,duration,matrix)
    except (KeyError,ValueError,TypeError,IndexError) as exc:
        raise HTTPException(400,'Données de calcul invalides.') from exc
    if matrix is not None and travel_matrix is None:result['routing']='osrm'
    result['live_traffic']=False
    return result

@app.post('/api/optimize')
def optimization(data:OptimizeRequest):
    return optimized(data.participants,data.venues,data.objective,data.start_at,data.duration,data.travel_matrix)
@app.post('/api/meetings')
def create_meeting(data:CreateMeeting):
    if data.venues is not None:
        validate_points(data.venues)
    identifier='m'+secrets.token_hex(12); token=secrets.token_urlsafe(24)
    payload={'id':identifier,'name':data.name,'date':data.date,'duration':data.duration,'objective':data.objective,'description':data.description,'venues':data.venues or [],'status':'collecting','chosen_venue':None,'organizer_email':data.organizer_email}
    store.create(payload,token)
    invite_path='/?'+urlencode({'join':identifier})
    admin_path='/?'+urlencode({'meeting':identifier,'admin':token})
    content=(f"Ta rencontre « {data.name} » est créée.\nDate : {data.date or 'à préciser'}\n\n"
             f"Ton lien privé organisateur (à conserver, ne pas partager) :\n{PUBLIC_APP_URL}{admin_path}\n\n"
             f"Lien à partager aux invités :\n{PUBLIC_APP_URL}{invite_path}")
    email_status=mailer.send(f'{identifier}:created',data.organizer_email,"meet’cool · Ta rencontre est créée",content)
    return {'meeting':payload,'admin_token':token,'invite_path':invite_path,'admin_path':admin_path,'email_status':email_status}

def retrieve(meeting_id):
    return store.retrieve(meeting_id)

@app.get('/api/meetings/{meeting_id}')
def get_meeting(meeting_id:str):
    row,meeting,participants=retrieve(meeting_id)
    # Privacy: guest-facing endpoint deliberately omits participant GPS coordinates.
    return {'meeting':{k:v for k,v in meeting.items() if k!='organizer_email'},'participants':[{'id':p['id'],'name':p['name'],'mode':p['mode'],'status':p.get('status','ready')} for p in participants]}

@app.post('/api/meetings/{meeting_id}/join')
def join(meeting_id:str,data:Guest):
    _,meeting,_=retrieve(meeting_id)
    if meeting['status']!='collecting':raise HTTPException(409,'Les réponses à cette rencontre sont fermées.')
    if not isfinite(data.lat) or not isfinite(data.lng):raise HTTPException(422,'Coordonnées invalides.')
    p=data.model_dump();p['id']='p'+secrets.token_hex(12);p['status']='accepted'
    store.add_participant(meeting_id,p)
    content=(f"Ton départ pour « {meeting['name']} » est enregistré.\nDate : {meeting.get('date') or 'à préciser'}\n"
             f"Retrouve le lieu une fois confirmé :\n{PUBLIC_APP_URL}/?join={meeting_id}")
    email_status=mailer.send(f"{meeting_id}:joined:{p['id']}",data.email,"meet’cool · Participation enregistrée",content)
    return {'participant_id':p['id'],'status':'registered','email_status':email_status}

@app.get('/api/meetings/{meeting_id}/admin')
def admin(meeting_id:str,token:str):
    row,meeting,participants=retrieve(meeting_id)
    if not secrets.compare_digest(token,row):raise HTTPException(403,'Invalid admin token')
    return {'meeting':meeting,'participants':participants}

@app.patch('/api/meetings/{meeting_id}/admin')
def update_meeting(meeting_id:str,data:MeetingUpdate,token:str):
    row,meeting,participants=retrieve(meeting_id)
    was_confirmed=meeting['status']=='confirmed'
    previous_venue=meeting.get('chosen_venue')
    if not secrets.compare_digest(token,row):raise HTTPException(403,'Invalid admin token')
    if data.objective in ('earliest','fair','total','minimax'):meeting['objective']=data.objective
    if data.venues is not None:
        if len(data.venues)>200:raise HTTPException(400,'Too many venues')
        validate_points(data.venues)
        for v in data.venues:
            if not all(k in v for k in ('id','name','lat','lng')):raise HTTPException(400,'Invalid venue')
        meeting['venues']=data.venues
        meeting['generated_venues']=False
    if data.status in ('collecting','confirmed','cancelled'):meeting['status']=data.status
    if data.chosen_venue is not None:
        if data.chosen_venue not in [v['id'] for v in meeting['venues']]:raise HTTPException(400,'Unknown venue')
        meeting['chosen_venue']=data.chosen_venue
    venue=next((v for v in meeting['venues'] if v['id']==meeting.get('chosen_venue')),None)
    if meeting['status']=='confirmed' and venue is None:
        raise HTTPException(400,'Choisis un lieu avant de confirmer la rencontre.')
    store.update(meeting)
    summary={}
    if meeting['status']=='confirmed' and (not was_confirmed or previous_venue!=meeting.get('chosen_venue')):
        links=google_maps_urls(venue['lat'],venue['lng'])
        content=(f"Le lieu de « {meeting['name']} » est confirmé : {venue['name']}.\n"
                 f"Date : {meeting.get('date') or 'à préciser'}\n\nVoir le lieu : {links['map']}\n"
                 f"Itinéraire : {links['directions']}\n\nTa rencontre : {PUBLIC_APP_URL}/?join={meeting_id}\n"
                 "Vérifie l’accès au lieu avant de partir.")
        recipients={p.get('email') for p in participants if p.get('email')}
        if meeting.get('organizer_email'):recipients.add(meeting['organizer_email'])
        for recipient in sorted(recipients):
            result=mailer.send(f"{meeting_id}:confirmed:{meeting['chosen_venue']}:{recipient}",recipient,"meet’cool · Le lieu est confirmé",content)
            summary[result]=summary.get(result,0)+1
    return {'meeting':meeting,'email_summary':summary}

def meeting_candidates(participants):
    """Indicative search points around the spherical centre of accepted departures."""
    x=y=z=0.0
    for p in participants:
        lat,lng=radians(p['lat']),radians(p['lng'])
        x+=cos(lat)*cos(lng);y+=cos(lat)*sin(lng);z+=sin(lat)
    lat=degrees(atan2(z,sqrt(x*x+y*y)));lng=degrees(atan2(y,x))
    return [{'id':f'common-{i}','name':name,'lat':max(-85,min(85,lat+dy)),
             'lng':(lng+dx+180)%360-180,'description':'Point indicatif · vérifier l’accès et choisir un lieu accessible'}
            for i,(name,dy,dx) in enumerate([('Votre point commun',0,0),('L’alternative au nord',.008,0),
                                           ('Le point côté est',0,.008),('L’alternative au sud',-.008,0)])]


@app.get('/api/meetings/{meeting_id}/analysis')
def analysis(meeting_id:str,token:str):
    row,meeting,participants=retrieve(meeting_id)
    if not secrets.compare_digest(token,row):raise HTTPException(403,'Invalid admin token')
    if not participants:return {'participants':[],'ranking':[],'matrix':[],'venues':[]}
    if not meeting['venues'] or meeting.get('generated_venues'):
        meeting['venues']=meeting_candidates(participants)
        meeting['generated_venues']=True
        store.update(meeting)
    result=optimized(participants,meeting['venues'],meeting['objective'],meeting.get('date'),meeting['duration'])
    result['venues']=meeting['venues']
    result['participants']=[{'id':p['id'],'name':p['name'],'mode':p['mode'],'lat':p['lat'],'lng':p['lng'],'location_source':p.get('location_source','planned'),'location_label':p.get('location_label',''),'status':p.get('status','accepted')} for p in participants]
    return result

@app.post('/api/meetings/{meeting_id}/participants/{pid}/status')
def status(meeting_id:str,pid:str,data:Status):
    # Non-location status demo; for production, authenticate participant with a private token.
    if data.state not in ('ready','en_route','arrived','delayed'):raise HTTPException(400,'Invalid state')
    raise HTTPException(501,'Requires participant authentication; intentionally disabled')

@app.get('/api/algorithms/demo')
def algorithms_demo():
    graph={'A':[('B',4),('C',12)],'B':[('C',3),('D',9)],'C':[('D',2)],'D':[]}
    distances,previous=dijkstra(graph,'A')
    closure=floyd_warshall(list(graph),[(u,v,w) for u,edges in graph.items() for v,w in edges])
    closure={u:{v:cost if isfinite(cost) else None for v,cost in row.items()} for u,row in closure.items()}
    return {'graph':graph,'dijkstra':{'distances':distances,'path_A_D':reconstruct_path(previous,'A','D')},'floyd_warshall':closure,'complexity':{'dijkstra':'O((V+E) log V)','floyd_warshall':'O(V³)','enumeration':'O(P × C) after matrix computation'}}
