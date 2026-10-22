'use client'
import {useEffect,useRef} from 'react'
export function useDialog(open:boolean,onClose:()=>void,busy=false){
 const close=useRef(onClose),blocked=useRef(busy);close.current=onClose;blocked.current=busy
 useEffect(()=>{if(!open)return;const before=document.activeElement as HTMLElement|null;const overflow=document.body.style.overflow;document.body.style.overflow='hidden'
 const focusable=()=>Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"] button:not(:disabled), [role="dialog"] a[href], [role="dialog"] input:not(:disabled), [role="dialog"] select:not(:disabled), [role="dialog"] textarea:not(:disabled)')).filter(e=>e.offsetParent!==null)
 const frame=requestAnimationFrame(()=>focusable()[0]?.focus())
 const key=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!blocked.current){e.preventDefault();close.current()}if(e.key==='Tab'){const all=focusable();if(!all.length){e.preventDefault();return}const first=all[0],last=all[all.length-1];if(e.shiftKey&&(document.activeElement===first||!document.querySelector('[role="dialog"]')?.contains(document.activeElement))){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}
 document.addEventListener('keydown',key);return()=>{cancelAnimationFrame(frame);document.removeEventListener('keydown',key);document.body.style.overflow=overflow;before?.focus()}
 },[open])
}
