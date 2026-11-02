"""Content-addressed image assets and same-fact text/image input bundles."""
import hashlib
import copy
import io
from pathlib import Path
from PIL import Image,PngImagePlugin
from ..common import read,write,digest,O4Error
from .facts import VERSION,FONT,visual_facts,card_facts
from .rendering import card_plan,scene_plan,png_bytes
from .verify import audit_facts,audit_card,audit_scene,audit_pixels,require
from .attachments import attach,checked_bytes


def page_png(cards,key):
    page=Image.new('RGB',(2080,580*((len(cards)+1)//2)),'white')
    for i,data in enumerate(cards):page.paste(Image.open(io.BytesIO(data)),((i%2)*1040,(i//2)*580))
    info=PngImagePlugin.PngInfo();info.add_text('rendering_version',VERSION);info.add_text('facts_digest',key)
    out=io.BytesIO();page.save(out,format='PNG',pnginfo=info,optimize=False,compress_level=6)
    return out.getvalue(),hashlib.sha256(page.tobytes()).hexdigest()


class AssetStore:
    def __init__(self,root):self.root=Path(root);self.assets={}
    def save(self,kind,key,data,pixel_sha,**extra):
        path=f'public/assets/{kind}_{key}.png';target=self.root/path
        if target.exists():
            if target.read_bytes()!=data:raise O4Error('asset_collision')
        else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        record={'path':path,'kind':kind,'content_digest':key,'sha256':hashlib.sha256(data).hexdigest(),'pixel_sha256':pixel_sha,**extra}
        self.assets[path]=record
        return record
    def card(self,data):
        key=digest(data);path=f'public/assets/card_{key}.png'
        if path in self.assets:return self.assets[path]
        plan=card_plan(data);audit_card(data,plan);png,psha=png_bytes(plan,key)
        return self.save('card',key,png,psha,plan=plan,public_facts=data)
    def scene(self,facts):
        key=facts['facts_digest'];path=f'public/assets/scene_{key}.png'
        if path in self.assets:return self.assets[path]
        plan=scene_plan(facts);audit_scene(facts,plan);png,psha=png_bytes(plan,key)
        return self.save('scene',key,png,psha,plan=plan,public_facts=facts)
    def page(self,cards):
        keys=[c['content_digest'] for c in cards];key=digest({'rendering_version':VERSION,'cards':keys})
        path=f'public/assets/page_{key}.png'
        if path in self.assets:return self.assets[path]
        png,psha=page_png([checked_bytes(self.root,c) for c in cards],key)
        return self.save('page',key,png,psha,cards=[c['path'] for c in cards])
    def build(self,source):
        facts=visual_facts(source);audit_facts(source,facts)
        cards=[self.card(card_facts(o)) for o in sorted(facts['objects'],key=lambda o:o['object_id'])]
        scene=self.scene(facts);pages=[self.page(cards[i:i+6]) for i in range(0,len(cards),6)]
        images=[scene,*pages]
        return {'schema_version':'o4_visual_bundle_v1','source':copy.deepcopy(source),'visual_facts':facts,
                'card_paths':[c['path'] for c in cards],'image_paths':[a['path'] for a in images],
                'text_input':attach(source,facts,images,self.root,with_images=False),
                'image_input':attach(source,facts,images,self.root,with_images=True)}


def audit_asset(root,asset,assets,font_path=FONT,*,repeat=False):
    kind=asset['kind'];required={'path','kind','content_digest','sha256','pixel_sha256'}|({'cards'} if kind=='page' else {'plan','public_facts'})
    require(set(asset)==required,'asset whitelist')
    data=checked_bytes(root,asset);key=asset['content_digest']
    if kind in ('card','scene'):
        facts=asset['public_facts'];plan=asset['plan']
        if kind=='card':
            require(key==digest(facts),'card content binding');audit_card(facts,plan)
        else:require(key==facts['facts_digest'],'scene content binding');audit_scene(facts,plan)
        hashes=audit_pixels(data,plan,key,font_path)
        if repeat:
            regenerated=card_plan(facts) if kind=='card' else scene_plan(facts)
            require(regenerated==plan,'deterministic primitive generation')
            second,_=png_bytes(regenerated,key);require(data==second,'deterministic repeated PNG bytes')
    elif kind=='page':
        parts=[assets[p] for p in asset['cards']]
        require(key==digest({'rendering_version':VERSION,'cards':[a['content_digest'] for a in parts]}),'page content binding')
        original=Image.open(io.BytesIO(data));original.load()
        expected=Image.new('RGB',(2080,((len(parts)+1)//2)*580),'white')
        for i,a in enumerate(parts):expected.paste(Image.open(io.BytesIO(checked_bytes(root,a))),((i%2)*1040,(i//2)*580))
        require(original.mode=='RGB' and original.size==expected.size and original.tobytes()==expected.tobytes(),'page actual pixels')
        require(original.info=={'rendering_version':VERSION,'facts_digest':key},'page metadata')
        hashes={'sha256':hashlib.sha256(data).hexdigest(),'pixel_sha256':hashlib.sha256(original.tobytes()).hexdigest()}
        if repeat:require(page_png([checked_bytes(root,a) for a in parts],key)[0]==data,'deterministic page')
    else:raise O4Error('invalid_visual_asset_kind')
    require(hashes['sha256']==asset['sha256'] and hashes['pixel_sha256']==asset['pixel_sha256'],'asset hash')
    return {'path':asset['path'],'kind':kind,'status':'PASS','repeated':repeat}


def audit_bundle(root,bundle,assets):
    require(set(bundle)=={'schema_version','source','visual_facts','card_paths','image_paths','text_input','image_input'},'bundle whitelist')
    source=bundle['source'];facts=bundle['visual_facts'];audit_facts(source,facts)
    expected_cards=[digest(card_facts(o)) for o in sorted(facts['objects'],key=lambda o:o['object_id'])]
    require([assets[p]['content_digest'] for p in bundle['card_paths']]==expected_cards,'all object cards covered')
    selected=[assets[p] for p in bundle['image_paths']]
    require(selected[0]['kind']=='scene' and selected[0]['content_digest']==facts['facts_digest'],'scene binding')
    actual_cards=[p for page in selected[1:] for p in page['cards']]
    require(actual_cards==bundle['card_paths'],'label pages completeness/order')
    for condition in ('text','image'):
        expected=attach(source,facts,selected,root,with_images=condition=='image')
        require(bundle[condition+'_input']==expected,'input envelope facts/images binding')
    return True
