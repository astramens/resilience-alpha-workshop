"""Run on the Windows Docker HOST, never on the attacker PC or in a container.

Only captures when the backend assigns a job. Raw images are never uploaded.
YuNet detects faces; SFace produces embeddings; the API compares to enrolled
embeddings. This prototype has NO anti-photo/liveness guarantee.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
MODEL_DIR=Path(__file__).resolve().parent/'models'
MODELS={
 'face_detection_yunet_2023mar.onnx':('face_detection_yunet','8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
 'face_recognition_sface_2021dec.onnx':('face_recognition_sface','0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79')
}


def download_models():
    MODEL_DIR.mkdir(exist_ok=True)
    for name,(folder,digest) in MODELS.items():
        target=MODEL_DIR/name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==digest:
            continue
        print('Telechargement du modele : '+name,flush=True)
        url='https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/'+folder+'/'+name
        req=Request(url,headers={'User-Agent':'Resilience-Alpha-Workshop'})
        with urlopen(req,timeout=120) as r:
            payload=r.read(50*1024*1024)
        if hashlib.sha256(payload).hexdigest()!=digest:
            raise RuntimeError('Empreinte du modele incorrecte : '+name)
        target.write_bytes(payload)


def config():
    p=ROOT/'.camera-agent.json'
    if not p.exists(): raise RuntimeError('Executez python scripts/face_setup.py avant cet agent.')
    return json.loads(p.read_text(encoding='utf-8-sig'))


def api(cfg,path,body=None):
    base=cfg['url'].rstrip('/')
    req=Request(base+'/api/'+path,data=None if body is None else json.dumps(body).encode(),
                headers={'Authorization':'Bearer '+cfg['token'],'Origin':base,'Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=8) as r: return json.load(r)
    except HTTPError as exc:
        try:
            message=json.load(exc).get('detail','Erreur API')
        except (ValueError,AttributeError): message='Erreur API'
        raise RuntimeError(str(exc.code)+' : '+str(message)) from None


def open_camera(index):
    import cv2
    cap=cv2.VideoCapture(index,cv2.CAP_DSHOW if sys.platform=='win32' else cv2.CAP_ANY)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError('Camera inaccessible. Fermez Camera/Teams et verifiez son index.')
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
    return cap


def preview(cfg,index):
    import cv2
    cap=open_camera(index)
    print('Verifiez que cette image provient de la camera USB externe. Q pour fermer.')
    try:
        while True:
            ok,frame=cap.read()
            if not ok: raise RuntimeError('Lecture camera impossible')
            cv2.imshow('Camera USB du PC Hote - Q pour fermer',frame)
            if cv2.waitKey(30)&255 in (ord('q'),27): break
    finally:
        cap.release();cv2.destroyAllWindows()
    if input('Est-ce bien la camera USB externe ? [oui/non] : ').strip().lower()=='oui':
        cfg['camera_index']=index
        p=ROOT/'.camera-agent.json'
        p.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        print('Index de camera enregistre.')


def capture(cfg,job,detector,recognizer):
    import cv2
    cap=None
    try:
        cap=open_camera(cfg['camera_index'])
        samples=[]
        started=time.monotonic();last_sample=0;last_check=0
        while time.monotonic()-started<20:
            now=time.monotonic()
            if now-last_check>=1:
                state=api(cfg,'face-agent/job/'+job['id'])
                last_check=now
                if state['stage']!='camera': return
            ok,frame=cap.read()
            if not ok: raise RuntimeError('Camera read error')
            clean=frame.copy()
            detector.setInputSize((frame.shape[1],frame.shape[0]))
            _,faces=detector.detect(clean)
            hint='Un seul visage, face a la camera - Echap pour annuler'
            if faces is not None and len(faces)==1:
                face=faces[0]
                x,y,w,h=[int(v) for v in face[:4]]
                cv2.rectangle(frame,(x,y),(x+w,y+h),(40,180,70),2)
                if w>=90 and h>=90 and now-last_sample>=0.6:
                    gray=cv2.cvtColor(clean[max(0,y):max(0,y)+h,max(0,x):max(0,x)+w],cv2.COLOR_BGR2GRAY)
                    if gray.size and cv2.Laplacian(gray,cv2.CV_64F).var()>30:
                        aligned=recognizer.alignCrop(clean,face)
                        samples.append(recognizer.feature(aligned).flatten().tolist())
                        last_sample=now
            cv2.putText(frame,hint,(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.42,(255,255,255),1)
            cv2.putText(frame,'Compte : '+job['username'],(10,50),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,255,255),1)
            cv2.imshow('Identification - camera du PC Hote',frame)
            key=cv2.waitKey(20)&255
            if key==27:
                api(cfg,'face-agent/result/'+job['id'],{'error':'capture_cancelled'})
                return
            if len(samples)>=3: break
        state=api(cfg,'face-agent/result/'+job['id'],{'features':samples})
        print('Resultat : '+state['stage'],flush=True)
        # Keep the camera active for the 30-second red signal on face rejection.
        while state.get('camera_on') and state['stage']=='face_rejected':
            ok,frame=cap.read()
            if ok:
                cv2.putText(frame,'Visage refuse - patientez 30 secondes',(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,255),1)
                cv2.imshow('Identification - camera du PC Hote',frame)
                cv2.waitKey(30)
            time.sleep(0.2)
            state=api(cfg,'face-agent/job/'+job['id'])
    except (RuntimeError,URLError) as exc:
        print('Erreur de capture : '+str(exc),flush=True)
        try: api(cfg,'face-agent/result/'+job['id'],{'error':'camera_unavailable'})
        except (RuntimeError,URLError): pass
    finally:
        if cap is not None: cap.release()
        cv2.destroyAllWindows()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['models','preview','bootstrap','run'])
    parser.add_argument('--index',type=int,default=0)
    args=parser.parse_args()
    if args.mode=='models': download_models();return
    cfg=config()
    if args.mode=='preview': preview(cfg,args.index);return
    import cv2
    download_models()
    detector=cv2.FaceDetectorYN.create(str(MODEL_DIR/'face_detection_yunet_2023mar.onnx'),'',(640,480),0.9,0.3,5000)
    recognizer=cv2.FaceRecognizerSF.create(str(MODEL_DIR/'face_recognition_sface_2021dec.onnx'),'')
    if args.mode=='bootstrap':
        username=input('Identifiant initial [operateur] : ').strip() or 'operateur'
        job=api(cfg,'face-agent/bootstrap',{'username':username,'password':getpass.getpass('Mot de passe actuel : ')})
        capture(cfg,job,detector,recognizer)
        return
    print('Agent pret. La camera reste eteinte tant qu aucune identification n est demandee.',flush=True)
    while True:
        try:
            result=api(cfg,'face-agent/next')
            if result.get('job'): capture(cfg,result['job'],detector,recognizer)
        except (RuntimeError,URLError) as exc:
            print('Connexion agent : '+str(exc),flush=True)
        time.sleep(1)


if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('\nAgent arrete. Camera liberee.')
    except Exception as exc: raise SystemExit(str(exc)) from None
