"""Reproduce static source audit into a NEW output, never into this frozen package."""
import argparse
import json
from pathlib import Path
from semantic_pallet_planner.jev_select.packaging_source_audit import *
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repo',default='.')
a=p.parse_args();repo=Path(a.repo);out=Path(a.output)
require(not out.exists(),'output_exists')
registration=load(Path(__file__).parent/'plan/source_audit_registration.json')
require(registration['version']==VERSION,'rule_version')
out.mkdir(parents=True)
def save(n,v):(out/n).write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
save('source_audit_registration.json',registration) # Before raw access.
files=historical_metadata(repo,out);e,aliases,inventory,errors=exposure_records(files,repo)
save('history_inventory.json',{'files':inventory,'parse_errors':errors})
require(not errors,'metadata_parse_errors')
save('exposure_records.json',e)
save('source_audit.json',audit_sources(load(repo/'raw/bed_bpp/bed-bpp_v1.json'),e,aliases))
