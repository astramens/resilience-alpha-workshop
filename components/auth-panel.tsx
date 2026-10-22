'use client'
import {useEffect,useRef,useState} from 'react'
import {ShieldCheck,Camera,ArrowUpRight} from 'lucide-react'
type Flow={stage:string;username:string;wait_seconds:number;blocked_seconds:number;camera_on:boolean;message?:string}
async function call(path:string,body?:unknown){
 const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
 const d=await r.json().catch(()=>({detail:'Reponse du serveur illisible.'}))
 if(!r.ok)throw Object.assign(new Error(typeof d.detail==='string'?d.detail:'Verifiez les champs saisis.'),{status:r.status})
 return d
}
export default function AuthPanel({onLogin}:{onLogin:(u:{username:string;role:string})=>void}){
 const [username,U]=useState(''),[password,P]=useState(''),[flow,F]=useState<Flow|null>(null),[error,E]=useState(''),[busy,B]=useState(false)
 const [status,S]=useState<{camera_agent_online:boolean;led_online:boolean}|null>(null)
 const polling=useRef(false),finishing=useRef(false)
 useEffect(()=>{let alive=true;const get=()=>call('auth/config').then(d=>{if(alive)S(d)}).catch(()=>{if(alive)S(null)});void get();const t=setInterval(get,3000);return()=>{alive=false;clearInterval(t)}},[])
 useEffect(()=>{
  if(!flow||!['camera','face_ok','success_wait'].includes(flow.stage))return
  let alive=true
  const poll=async()=>{
   if(polling.current)return;polling.current=true
   try{
    const next:Flow=await call('auth/face-status');if(!alive)return;F(next)
    if(['face_rejected','password_rejected','camera_error'].includes(next.stage)){U('');P('')}
    if(next.stage==='success_wait'&&next.wait_seconds===0&&!finishing.current){finishing.current=true;try{onLogin(await call('auth/finish',{}))}finally{finishing.current=false}}
   }catch(e){if(alive){E((e as Error).message);F(null);P('')}}finally{polling.current=false}
  }
  void poll();const t=setInterval(poll,1000);return()=>{alive=false;clearInterval(t)}
 },[flow?.stage,onLogin])
 useEffect(()=>{
  if(!flow||!['face_rejected','password_rejected'].includes(flow.stage))return
  const t=setInterval(()=>F(f=>f?{...f,wait_seconds:Math.max(0,f.wait_seconds-1),blocked_seconds:Math.max(0,f.blocked_seconds-1)}:f),1000)
  return()=>clearInterval(t)
 },[flow?.stage])
 async function identify(e:React.FormEvent){e.preventDefault();B(true);E('');try{F(await call('auth/identify',{username}))}catch(e){E((e as Error).message);U('')}finally{B(false)}}
 async function login(e:React.FormEvent){e.preventDefault();B(true);E('');try{const d=await call('auth/login',{password});F(d);P('');if(d.stage==='password_rejected'){U('');E(d.message)}}catch(e){E((e as Error).message)}finally{B(false)}}
 async function reset(){B(true);E('');try{await call('auth/cancel',{});F(null);U('');P('')}catch(e){if((e as {status?:number}).status===401){F(null);U('');P('')}else E((e as Error).message)}finally{B(false)}}
 const failed=flow&&['face_rejected','password_rejected','camera_error'].includes(flow.stage)
 return <main className="login"><section className="story"><div className="brand">R <span>REARM / ATELIER</span></div><div><p className="eyebrow">ACCES AU BACK-OFFICE</p><h1>Votre compte.<br/>Votre visage.<br/><em>Votre acces.</em></h1><p>Identification par la camera USB du PC Hote, puis verification du mot de passe.</p></div><small>WORKSHOP M2 · 2026 / 2027</small></section><section className="login-right"><div><ShieldCheck size={32}/><p className="eyebrow">ESPACE ÉQUIPE</p><h2>Connexion</h2><p className="hint">Camera du PC Hote : {status?.camera_agent_online?'agent connecte':'agent hors ligne'}<br/>ESP8266 : {status?.led_online?'module connecte':'non connecte'}</p>
 {!flow&&<form onSubmit={identify}><label>Identifiant<input name="username" required autoComplete="username" maxLength={80} pattern="[A-Za-z0-9._-]+" value={username} onChange={e=>U(e.target.value)}/></label><button className="primary" disabled={busy||!status?.camera_agent_online}>{busy?'Identification...':'Verifier mon visage'}<Camera size={17}/></button></form>}
 {flow?.stage==='camera'&&<div className="feedback success" role="status">Camera active sur le PC Hote. Placez-vous seul devant la camera USB et regardez l objectif.</div>}
 {flow?.stage==='face_ok'&&<><p className="feedback success">Visage reconnu pour {flow.username}. Vous pouvez saisir votre mot de passe.</p><form onSubmit={login}><label>Mot de passe<input autoFocus name="password" type="password" required autoComplete="current-password" maxLength={256} value={password} onChange={e=>P(e.target.value)}/></label><button className="primary" disabled={busy}>{busy?'Verification...':'Se connecter'}<ArrowUpRight size={17}/></button></form></>}
 {flow?.stage==='success_wait'&&<p className="feedback success" role="status">Mot de passe valide. Signal vert fixe : {flow.wait_seconds} s. Ouverture du back-office a la fin du signal.</p>}
 {failed&&<><p className="feedback error" role="alert">{flow.stage==='face_rejected'?'Visage non reconnu. L identifiant a ete efface.':flow.stage==='camera_error'?'Capture impossible ou annulee. Verifiez la camera du PC Hote.':'Mot de passe refuse. Reprenez l identification.'}{flow.wait_seconds>0&&<> Signal lumineux en cours : {flow.wait_seconds} s.</>}{flow.blocked_seconds>0&&<> Blocage restant : {flow.blocked_seconds} s.</>}</p><button className="secondary" disabled={busy||flow.wait_seconds>0||flow.blocked_seconds>0} onClick={reset}>Recommencer</button></>}
 {flow&&flow.stage==='face_ok'&&<button className="text-button" onClick={reset} disabled={busy}>Changer d identifiant</button>}
 {error&&<p className="feedback error" role="alert">{error}</p>}
 <p className="hint">Le mot de passe ne suffit pas seul. Les images restent sur le PC Hote ; seules les empreintes faciales sont envoyees a votre serveur local.</p></div></section></main>
}
