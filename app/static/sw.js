const APP_VERSION="3.2.2";
const CACHE_NAME=`table-tale-${APP_VERSION}`;
const CORE=[
  `/styles.css?v=${APP_VERSION}`,
  `/app.js?v=${APP_VERSION}`,
  `/manifest.webmanifest?v=${APP_VERSION}`,
  `/brand-mark.svg?v=${APP_VERSION}`
];

self.addEventListener("install",event=>{
  event.waitUntil((async()=>{
    const cache=await caches.open(CACHE_NAME);
    await cache.addAll(CORE);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate",event=>{
  event.waitUntil((async()=>{
    const keys=await caches.keys();
    await Promise.all(keys.filter(k=>k!==CACHE_NAME).map(k=>caches.delete(k)));
    await self.clients.claim();

    // Existing v2/v3.2 pages may still be controlled by the old cache-first
    // worker. Navigate each open app window to a versioned URL once so that
    // the request cannot match the old "/" cache entry.
    const windows=await self.clients.matchAll({type:"window",includeUncontrolled:true});
    for(const client of windows){
      try{
        const url=new URL(client.url);
        if(url.origin!==self.location.origin) continue;
        if(url.searchParams.get("_appv")===APP_VERSION) continue;
        url.searchParams.set("_appv",APP_VERSION);
        await client.navigate(url.href);
      }catch(_){}
    }
  })());
});

self.addEventListener("fetch",event=>{
  const req=event.request;
  const url=new URL(req.url);

  if(url.origin!==self.location.origin) return;
  if(url.pathname.startsWith("/api/")||url.pathname.startsWith("/uploads/")||url.pathname==="/health") return;

  if(req.mode==="navigate"){
    event.respondWith((async()=>{
      try{
        const fresh=await fetch(req,{cache:"no-store"});
        return fresh;
      }catch(_){
        return (await caches.match(req)) || (await caches.match("/")) || Response.error();
      }
    })());
    return;
  }

  if(req.method!=="GET") return;

  event.respondWith((async()=>{
    const cache=await caches.open(CACHE_NAME);
    const cached=await cache.match(req);
    const network=fetch(req).then(resp=>{
      if(resp && resp.ok) cache.put(req,resp.clone());
      return resp;
    }).catch(()=>null);
    return cached || (await network) || Response.error();
  })());
});
