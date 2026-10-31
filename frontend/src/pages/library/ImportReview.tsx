import { useEffect, useRef, useState } from 'react'
import { libraryApi, apiErrorMessage } from '../../lib/api'
import { fields, labels } from '../../lib/library'
import type { Choice, Material, Preview } from '../../lib/library'

export default function ImportReview({material, disabled = false, onDone}: {material: Material; disabled?: boolean; onDone?: () => void}) {
  const [preview,setPreview] = useState<Preview|null>(null)
  const [choices,setChoices] = useState<Choice[]>([])
  const [error,setError] = useState('')
  const [message,setMessage] = useState('')
  const [busy,setBusy] = useState(false)
  const [confirmed,setConfirmed] = useState(false)
  const [retry,setRetry] = useState(0)
  const epoch=useRef(0), lock=useRef(false)
  const signature=JSON.stringify(material)
  useEffect(() => {
    const token=++epoch.current
    setPreview(null); setMessage(''); setError(''); setConfirmed(false); setBusy(true)
    libraryApi.preview(material).then(p => {
      if(epoch.current!==token) return
      setPreview(p); setChoices(p.items.map(i => ({action:i.status==='new'?'new':'skip', fields:[],replace_fields:[]})))
    }).catch(e => {if(epoch.current===token)setError(apiErrorMessage(e))}).finally(() => {if(epoch.current===token)setBusy(false)})
    return () => {++epoch.current}
  },[signature,retry])
  const patch=(index:number, change:Partial<Choice>) => {setChoices(old=>old.map((c,i)=>i===index?{...c,...change}:c));setConfirmed(false)}
  const save=async()=>{
    if(!preview || busy || lock.current || disabled || !confirmed)return
    const token=epoch.current; lock.current=true;setBusy(true);setError('')
    try{
      const result=await libraryApi.apply({...material,profile:material.legacy_id?undefined:{...preview.profile,user_confirmed:true}},preview.revision,choices)
      if(epoch.current!==token)return
      setPreview(null);setMessage(result.changed?'已保存 '+result.changed+' 项卡片变更。相同内容已跳过。':'没有新增事实，未生成重复卡片。');onDone?.()
    }catch(e){if(epoch.current===token)setError(apiErrorMessage(e))}
    finally{lock.current=false;if(epoch.current===token)setBusy(false)}
  }
  return <section className="library-review" aria-label="经历导入查重"><h3>导入前查重</h3><p>相同事实跳过；相似项目仅提示候选。请核对归属、时间和数据，再确认保存。系统不会自动扩写事实。</p>
    {busy&&<p role="status">正在处理…</p>}{error&&<p role="alert">{error} <button type="button" onClick={()=>setRetry(v=>v+1)}>重新查重</button></p>}{message&&<p role="status">{message}</p>}
    {disabled&&material.profile&&!material.profile.user_confirmed&&<p className="warning-note">请先在工作台核对并确认事实，再操作导入。</p>}
    {preview&&<fieldset disabled={busy||disabled}>
      {preview.items.map((item,index)=>{const choice=choices[index];const target=item.candidates.find(c=>c.id===choice?.target);return <article className="library-card" key={index}><h4>{item.incoming.name||'未命名经历'} · {item.status==='same'?'相同事实':item.status==='review'?'发现可能相同的经历':'新经历'}</h4>
        <p>{item.incoming.role} {item.incoming.period}</p>
        <label>处理方式<select aria-label={'处理方式'+(index+1)} value={choice.action} onChange={e=>patch(index,{action:e.target.value as Choice['action'],target:undefined,fields:[],replace_fields:[]})}><option value="skip">跳过</option><option value="new">作为独立新卡片</option>{item.candidates.length>0&&<option value="merge">归入已有卡片</option>}</select></label>
        {choice.action==='merge'&&<><label>已有卡片<select value={choice.target||''} onChange={e=>patch(index,{target:e.target.value,fields:[],replace_fields:[]})}><option value="">请选择，避免合并不同项目</option>{item.candidates.map(c=><option key={c.id} value={c.id}>{c.facts.name} · {c.facts.period} · {c.facts.role}</option>)}</select></label><p>每个字段默认保留旧内容。补充只追加新条目；数据冲突时请明确选择替换或保留。</p></>}
        {fields.filter(k=>item.incoming.kind!=='education'||!['actions','results','skills'].includes(k)).map(k=><div className="library-diff" key={k}><strong>{labels[k]}</strong>{target?.conflicts?.includes(k)&&<p role="status">同一表述中的数字不同，请保留原值或明确采用新材料替换；旧值与来源仍保存在历史中。</p>}{target&&<p>原有：{Array.isArray(target.facts[k])?(target.facts[k] as string[]).join('；'):target.facts[k]||'空'}</p>}<p>材料：{Array.isArray(item.incoming[k])?(item.incoming[k] as string[]).join('；'):item.incoming[k]||'空'}</p>{target&&JSON.stringify(target.facts[k])!==JSON.stringify(item.incoming[k])&&<select aria-label={labels[k]+'处理方式'} value={!choice.fields.includes(k)?'keep':choice.replace_fields.includes(k)?'replace':'add'} onChange={e=>patch(index,{fields:[...choice.fields.filter(f=>f!==k),...(e.target.value==='keep'?[]:[k])],replace_fields:[...choice.replace_fields.filter(f=>f!==k),...(e.target.value==='replace'?[k]:[])]})}><option value="keep">保留原有</option>{Array.isArray(item.incoming[k])?<><option value="add" disabled={target.conflicts?.includes(k)}>补充材料中的新条目（核对无矛盾后选）</option><option value="replace">采用材料此字段全部内容（替换）</option></>:<option value="add">采用材料此字段（替换）</option>}</select>}</div>)}
      </article>})}
      {!!preview.education_notes.length&&<p className="warning-note">旧教育文本保留在来源里，不自动转成描述。请在工作台用教育卡核对学校、专业学历和起止时间：{preview.education_notes.join('；')}</p>}
      <label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>我已核对每项归属、事实及所选替换 / 补充内容。</label>
      <button type="button" className="primary-button" disabled={!confirmed||choices.some(c=>c.action==='merge'&&!c.target)} onClick={()=>void save()}>确认导入</button>
    </fieldset>}
  </section>
}
