import { NextRequest } from 'next/server';
export const runtime='nodejs';
async function forward(req:NextRequest,{params}:{params:Promise<{path:string[]}>}) {
  const {path}=await params;
  if(path.some(p=>!p||p==='.'||p==='..'||p.includes('/')||p.includes('\\')))return Response.json({detail:'Invalid path'},{status:400});
  if(req.method!=='GET'&&req.headers.get('origin')&&req.headers.get('origin')!==req.nextUrl.origin)return Response.json({detail:'Untrusted origin'},{status:403});
  const base=process.env.FACTORY_API_URL||'http://127.0.0.1:8000';
  const headers:Record<string,string>={'Content-Type':'application/json','Cookie':req.headers.get('cookie')||''};
  const body=req.method==='GET'?undefined:await req.text();
  if(body&&new TextEncoder().encode(body).length>64000)return Response.json({detail:'Request too large'},{status:413});
  try {
    const r=await fetch(`${base}/factory/${path.map(encodeURIComponent).join('/')}`,{method:req.method,headers,body,signal:AbortSignal.timeout(90000),cache:'no-store',redirect:'error'});
    const out=new Headers({'Content-Type':r.headers.get('content-type')||'application/json','Cache-Control':'no-store'});
    const cookie=r.headers.get('set-cookie');if(cookie)out.set('set-cookie',req.nextUrl.protocol==='https:'&&!/;\s*secure/i.test(cookie)?cookie+'; Secure':cookie);
    const attachment=r.headers.get('content-disposition');if(attachment)out.set('content-disposition',attachment);
    return new Response(r.body,{status:r.status,headers:out});
  } catch {return Response.json({detail:'Factory API unavailable. Start the backend or configure FACTORY_API_URL.'},{status:503});}
}
export {forward as GET,forward as POST};
