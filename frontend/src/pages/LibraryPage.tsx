import { useEffect, useRef, useState } from 'react'
import { api, libraryApi, apiErrorMessage } from '../lib/api'
import { assembled } from '../lib/library'
import type { Bank, Material } from '../lib/library'
import type { ResumeProfile } from '../lib/types'
import ImportReview from './library/ImportReview'
import './library/library.css'
interface Props {userId:string; currentProfile:ResumeProfile|null; resumeName:string; disabled?:boolean;hasUnsaved?:boolean;onLoad:(profile:ResumeProfile,meta:{name:string})=>void}
export default function LibraryPage({userId,currentProfile,resumeName,disabled,onLoad}:Props){
 const [kindTab,setKindTab]=useState<'all'|string>('all')
 const [bank,setBank]=useState<Bank|null>(null),[error,setError]=useState(''),[selected,setSelected]=useState<string[]>([]),[material,setMaterial]=useState<Material|null>(null),[trash,setTrash]=useState(false),[loadConfirm,setLoadConfirm]=useState(false),[busy,setBusy]=useState(false),[archive,setArchive]=useState<ResumeProfile|null>(null)
 const epoch=useRef(0), lock=useRef(false), mounted=useRef(true)
 const refresh=async()=>{const token=++epoch.current;try{const b=await libraryApi.list();if(epoch.current===token){setBank(b);setKindTab(current=>{if(current!=='all')return current;const kinds=['education','project','internship','other'];const alive=b.cards.filter(c=>!c.deleted);if(alive.length<=6)return 'all';const countOf=(kind:string)=>alive.filter(c=>kind==='other'?!['education','project','internship'].includes(c.kind):c.kind===kind).length;const busiest=kinds.map(kind=>[kind,countOf(kind)] as const).sort((a,b)=>b[1]-a[1])[0];return busiest&&busiest[1]>0?busiest[0]:'all'});setSelected(old=>old.filter(id=>b.cards.some(c=>c.id===id&&!c.deleted)));setError('')}}catch(e){if(epoch.current===token)setError(apiErrorMessage(e))}}
 useEffect(()=>{mounted.current=true;void refresh();return()=>{mounted.current=false;++epoch.current}},[userId])
 const act=async(id:string,action:'delete'|'restore'|'revert',version?:number)=>{if(!bank||disabled||lock.current)return;lock.current=true;setBusy(true);const token=epoch.current;try{await libraryApi.action(id,userId,bank.revision,action,version);if(token===epoch.current)await refresh()}catch(e){if(token===epoch.current)setError(apiErrorMessage(e))}finally{lock.current=false;if(mounted.current)setBusy(false)}}
 const legacy=async(id:string)=>{const token=epoch.current;try{const r=await api.loadProfile(id);if(token===epoch.current&&r.profile)setArchive(r.profile)}catch(e){if(token===epoch.current)setError(apiErrorMessage(e))}}
 const done=()=>{void refresh()}
 return <div className="library-page"><section className="panel"><h2>个人经历库</h2><p>一个项目一张卡片。上传材料后在工作台核对，再查重入库；已有事实不会因重复上传而多存一份。</p>{error&&<p role="alert">{error}<button onClick={()=>void refresh()}>刷新经历库</button></p>}
 <fieldset disabled={disabled||busy}><button className="secondary-button" onClick={()=>{setTrash(!trash);setLoadConfirm(false)}}>{trash?'返回经历卡片':'回收站'}</button>{currentProfile&&<button className="secondary-button" onClick={()=>setMaterial({expected_user_id:userId,profile:currentProfile,source_name:resumeName})}>整理工作台材料</button>}
 {!trash&&<button className="primary-button" disabled={!selected.length} onClick={()=>setLoadConfirm(true)}>将所选 {selected.length} 张卡片载入工作台</button>}
 {loadConfirm&&<div className="warning-note library-load-confirm" role="dialog" aria-label="确认载入卡片"><p>所选卡片将替换工作台材料并清空当前简历稿，保留目标岗位 JD。载入后需要重新确认事实。</p><div className="library-confirm-actions"><button className="primary-button" onClick={()=>{if(bank)onLoad(assembled(bank.cards.filter(c=>selected.includes(c.id)&&!c.deleted),currentProfile?.name||''),{name:'经历库所选卡片'})}}>确认替换并载入</button><button className="secondary-button" onClick={()=>setLoadConfirm(false)}>取消</button></div></div>}
 </fieldset></section>
 {material&&<section className="panel library-import-panel"><div className="library-import-toolbar"><button type="button" className="primary-button library-close-preview" onClick={()=>setMaterial(null)}>关闭导入预览</button></div><ImportReview key={JSON.stringify(material)} material={material} disabled={disabled||(!material.legacy_id&&!material.profile?.user_confirmed)} onDone={done}/></section>}
 {bank&&(()=>{
   const labels:{[k:string]:string}={education:'教育经历',project:'项目经历',internship:'工作 / 实习',other:'其他经历'}
   const kinds=['education','project','internship','other']
   const cardsOf=(kind:string)=>bank.cards.filter(c=>c.deleted===trash&&(kind==='other'?!['education','project','internship'].includes(c.kind):c.kind===kind))
   const counts=kinds.reduce<{[k:string]:number}>((acc,kind)=>{acc[kind]=cardsOf(kind).length;return acc},{})
   const total=kinds.reduce((sum,kind)=>sum+counts[kind],0)
   const visible=kinds.filter(kind=>(kindTab==='all'?counts[kind]>0:kind===kindTab)&&counts[kind]>0)
   return <>
   <p className="library-kind-hint">卡片多于 6 张时默认只显示一个分类，点页签切换；点「全部」可一起看。</p>
   <nav className="library-kind-tabs" aria-label="按经历分类查看">
     <button type="button" aria-pressed={kindTab==='all'} className={kindTab==='all'?'active':''}
       onClick={()=>setKindTab('all')}>全部<span>{total}</span></button>
     {kinds.map(kind=><button key={kind} type="button" aria-pressed={kindTab===kind}
       className={kindTab===kind?'active':''} disabled={counts[kind]===0}
       onClick={()=>setKindTab(kind)}>{labels[kind]}<span>{counts[kind]}</span></button>)}
   </nav>
   {visible.length===0&&<p className="panel library-kind-empty">{trash?'回收站为空。':'这个分类还没有卡片。'}</p>}
   {visible.map(kind=>{const cards=cardsOf(kind);return <section key={kind}><h3>{labels[kind]}</h3><div className="library-grid">{[0,1].map(column=><div className="library-column" key={column}>{cards.filter((_,index)=>index%2===column).map(card=><article className="panel library-card" key={card.id} style={{order:cards.indexOf(card)}}>
 {!trash&&<label><input type="checkbox" disabled={disabled||busy} checked={selected.includes(card.id)} onChange={e=>{setSelected(old=>e.target.checked?[...old,card.id]:old.filter(id=>id!==card.id));setLoadConfirm(false)}}/>选择此卡片</label>}<details className="library-card-disclosure"><summary className="library-card-heading"><h3>{card.name}</h3><span className="library-card-toggle" aria-hidden="true" /></summary><div className="library-card-body"><p>{card.role} · {card.period||'时间未填写'}</p>{card.kind!=='education'&&<><ul>{card.actions.map((x,i)=><li key={i}>{x}</li>)}</ul><ul>{card.results.map((x,i)=><li key={i}>{x}</li>)}</ul><p>{card.skills.join(' · ')}</p></>}
 <div className="library-card-actions"><button className="library-card-action" disabled={disabled||busy} onClick={()=>void act(card.id,trash?'restore':'delete')}>{trash?'恢复卡片':'移入回收站'}</button>
 <details className="library-card-history"><summary className="library-card-action">来源与修改历史（{card.history.length}）</summary>{card.source_ids.map(id=>{const source=bank.sources.find(s=>s.id===id);return source&&<details key={id}><summary>{source.name} · {source.at}</summary><pre>{source.profile.raw_text||'该材料未提供文字原文，以下为解析事实。'}</pre><pre>{JSON.stringify(source.profile,null,2)}</pre></details>})}{card.history.map((v,i)=><details key={i}><summary>版本 {i+1} · {v.at}{v.deleted?' · 已移入回收站':''}</summary><pre>{JSON.stringify(v.facts,null,2)}</pre><button disabled={disabled||busy||trash} onClick={()=>void act(card.id,'revert',i)}>采用此版本的事实</button></details>)}</details>
 </div></div></details></article>)}</div>)}</div></section>})}</>})()}
 {bank&&!bank.cards.some(c=>c.deleted===trash)&&<p className="panel">{trash?'回收站为空。':'尚无经历卡片。请在工作台整理材料，或从下方历史材料确认导入。'}</p>}
 {!!bank?.legacy.length&&<section className="panel"><h3>历史材料</h3><p>旧版保存的完整材料仍保留。逐份预览查重后整理为卡片；不会删除原记录。</p>{bank.legacy.map(l=><div className="library-archive" key={l.id}><span>{l.name} · {l.saved_at} {bank.migrated.includes(l.id)?'（已整理）':''}</span><button disabled={busy||disabled} onClick={()=>void legacy(l.id)}>查看原记录</button><button disabled={busy||disabled} onClick={()=>setMaterial({expected_user_id:userId,legacy_id:l.id,source_name:l.name})}>预览整理</button></div>)}{archive&&<details open><summary>原记录内容</summary><pre>{JSON.stringify(archive,null,2)}</pre></details>}</section>}
 </div>
}
