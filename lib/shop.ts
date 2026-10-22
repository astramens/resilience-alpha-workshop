export type Product={id:number;sku:string;name:string;category:string;description:string;grade:string;price_cents:number;stock:number;image:string;workshop_note:string;active?:boolean;version?:number}
export type Customer={id:number;username:string;display_name:string}
export type Order={id:number;customer_id:number;number:string;recipient:string;status:string;total_cents:number;created_at:string;payment:string;payment_status?:string;checkout_url?:string|null;items:{product_id:number;name:string;sku:string;quantity:number;unit_price_cents:number}[]}
export const categories:Record<string,string>={pistolets:'Répliques de poing',fusils:'Répliques longues',arbaletes:'Arbalètes de décor',lames:'Lames de scène',effets:'Effets & maquettes'}
export const statuses:Record<string,string>={awaiting_payment:'En attente de paiement',confirmed:'Confirmée',preparing:'En préparation',ready:'Prête au retrait',collected:'Retirée',cancelled:'Annulée'}
export const money=(n:number)=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR'}).format(n/100)
export const date=(d:string)=>new Date(d).toLocaleString('fr-FR',{dateStyle:'medium',timeStyle:'short'})
export async function api<T=any>(path:string,body?:unknown):Promise<T>{
 const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
 const d=await r.json().catch(()=>({detail:'Réponse du serveur illisible.'}))
 if(!r.ok){const message=typeof d.detail==='string'?d.detail:Array.isArray(d.detail)?d.detail.map((e:{msg:string})=>e.msg).join(' · '):'Requête impossible.';throw Object.assign(new Error(message),{status:r.status})}
 return d
}
// crypto.randomUUID is unavailable on HTTP hotspot addresses; getRandomValues works there.
export function requestId(){
 if(typeof crypto.randomUUID==='function')return crypto.randomUUID()
 const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128
 const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')
 return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`
}
