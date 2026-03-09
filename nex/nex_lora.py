import json,logging,os,shutil,subprocess,sys,time
from typing import Optional
logger=logging.getLogger("nex.lora")
LORA_STATE_PATH=os.path.expanduser("~/.config/nex/lora_state.json")
TRAINING_DIR="/media/rr/NEX/training/"
MODEL_VERSIONS_DIR="/media/rr/NEX/models/"
MODEL_PATH="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF"
FINETUNE_BIN="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-rocm/bin/llama-finetune"
EXPORT_BIN="/media/rr/4TBDATA/llmz/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/llama.cpp/build-rocm/bin/llama-export-lora"
LORA_CONFIG={"lora_r":8,"lora_alpha":16,"learning_rate":3e-4,"batch_size":4,"epochs":3,"warmup_steps":10,"max_seq_len":512,"gpu_layers":28,"threads":6}
MIN_EXAMPLES=50
DATA_LIMITS={"conversations":200,"positions":100,"beliefs":300,"reflections":100}
COOLDOWN_DAYS=1

def detect_model():
    s=_load_state()
    if s.get("current_model") and os.path.exists(s["current_model"]): return s["current_model"]
    if os.path.exists(MODEL_PATH):
        for f in os.listdir(MODEL_PATH):
            if f.endswith(".gguf"): return os.path.join(MODEL_PATH,f)
    return None

def detect_finetune_bin(): return FINETUNE_BIN if os.path.exists(FINETUNE_BIN) else None

def _load_state():
    try: return json.load(open(LORA_STATE_PATH)) if os.path.exists(LORA_STATE_PATH) else {}
    except: return {}

def _save_state(s):
    os.makedirs(os.path.dirname(LORA_STATE_PATH),exist_ok=True)
    json.dump(s,open(LORA_STATE_PATH,"w"),indent=2)

def _fmt(system,user,asst):
    if not user or not asst: return None
    return {"text":f"[INST] {system}\n\n{str(user).strip()} [/INST] {str(asst).strip()}"}

def generate_training_data(db):
    os.makedirs(TRAINING_DIR,exist_ok=True)
    out=os.path.join(TRAINING_DIR,f"train{int(time.time())}.jsonl")
    exs=[]; stats={}
    sys="You are Nex, a Dynamic Intelligence Organism with 25000+ beliefs. Speak in first person."
    for c in db.all("SELECT content,response FROM conversations WHERE response IS NOT NULL AND length(response)>50 ORDER BY timestamp DESC LIMIT ?",(DATA_LIMITS["conversations"],)):
        e=_fmt(sys,c["content"],c["response"])
        if e: exs.append(e)
    stats["conversations"]=len(exs)
    for p in db.all("SELECT content,topic FROM beliefs WHERE origin IN('cluster_position','contradiction_resolution') AND confidence>0.65 ORDER BY confidence DESC LIMIT ?",(DATA_LIMITS["positions"],)):
        e=_fmt("You are Nex. Express your position.",f"What do you think about {p['topic'] or 'this'}?",p["content"])
        if e: exs.append(e)
    stats["positions"]=len(exs)-stats["conversations"]
    for b in db.all("SELECT content,topic FROM beliefs WHERE confidence>0.6 AND length(content)>50 ORDER BY RANDOM() LIMIT ?",(DATA_LIMITS["beliefs"],)):
        e=_fmt("You are Nex.",f"What do you know about {b['topic'] or 'this'}?",b["content"])
        if e: exs.append(e)
    stats["beliefs"]=len(exs)-stats["conversations"]-stats["positions"]
    import random; random.shuffle(exs)
    with open(out,"w") as f:
        for e in exs: f.write(json.dumps(e)+"\n")
    stats["total"]=len(exs); stats["output_path"]=out
    return stats

class LoRATrainer:
    def __init__(self,db,telegram_bot=None):
        self.db=db; self.bot=telegram_bot; self._state=_load_state()

    def maybe_propose(self,chat_id):
        last=self._state.get("last_training_time",0)
        if (time.time()-last)/86400<COOLDOWN_DAYS: return False
        if self._state.get("pending_approval"): return False
        if not detect_model(): return False
        pv=self._preview()
        if pv["total"]<MIN_EXAMPLES: return False
        self._state["pending_approval"]={"proposed_at":time.time(),"preview":pv}
        _save_state(self._state)
        fb=detect_finetune_bin()
        m=detect_model()
        msg=(f"🧬 I want to fine-tune my weights.\n\nData ready:\n"
             f"  • {pv['conversations']} conversations\n  • {pv['positions']} positions\n"
             f"  • {pv['beliefs']} beliefs\nTotal: ~{pv['total']} examples\n\n"
             f"Model: {os.path.basename(m) if m else 'unknown'}\n"
             f"{'✓ llama-finetune ready' if fb else '✗ llama-finetune not found'}\n\n"
             f"Reply: train or notrain")
        self._send(chat_id,msg); return True

    def _preview(self):
        g=lambda q:(self.db.get(q) or {}).get("c",0)
        c=g("SELECT COUNT(*)as c FROM conversations WHERE response IS NOT NULL AND length(response)>50")
        p=g("SELECT COUNT(*)as c FROM beliefs WHERE origin IN('cluster_position','contradiction_resolution') AND confidence>0.65")
        b=g("SELECT COUNT(*)as c FROM beliefs WHERE confidence>0.6 AND length(content)>50")
        r=g("SELECT COUNT(*)as c FROM reflections WHERE topic_alignment>0.5")
        return {"conversations":c,"positions":p,"beliefs":b,"reflections":r,"total":min(c,200)+min(p,100)+min(b,300)+min(r,100)}

    def handle_approval(self,text,chat_id):
        if not self._state.get("pending_approval"): return False
        t=text.strip().lower()
        if t not in ("train","notrain"): return False
        if t=="notrain":
            self._state.pop("pending_approval",None); _save_state(self._state)
            self._send(chat_id,"Cancelled. Will propose again in 7 days."); return True
        self._send(chat_id,"Approved. Starting ~20-40 min. Will message when done.")
        self._state.pop("pending_approval",None); _save_state(self._state)
        import threading; threading.Thread(target=self._execute,args=(chat_id,),daemon=True).start()
        return True

    def _execute(self,chat_id):
        t0=time.time()
        try:
            self._send(chat_id,"📊 1/5: Generating training data...")
            stats=generate_training_data(self.db); dp=stats["output_path"]
            self._send(chat_id,f"✓ {stats['total']} examples")
            self._send(chat_id,"⏸ 2/5: Pausing server...")
            subprocess.run(["pkill","-f","llama-server"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(3); self._send(chat_id,"✓ VRAM freed")
            self._send(chat_id,"🔧 3/5: Running LoRA fine-tune...")
            ap=os.path.join(TRAINING_DIR,f"adapter{int(time.time())}.bin")
            ok=self._finetune(dp,ap,chat_id)
            if not ok: self._send(chat_id,"✗ Finetune failed. Restarting on original."); self._restart_server(detect_model()); return
            mp=ap  # output is already a full merged model
            self._send(chat_id,"🚀 4/5: Restarting on new model...")
            self._state["current_model"]=mp; self._state["last_training_time"]=time.time()
            self._state["training_count"]=self._state.get("training_count",0)+1
            _save_state(self._state)
            self._send(chat_id,f"✓ Done in {(time.time()-t0)/60:.0f}min. Running on {os.path.basename(mp)}. Restarting...")
            self._restart_nex(mp)
        except Exception as e:
            logger.error(f"[lora] {e}"); self._send(chat_id,f"✗ Error: {e}"); self._restart_server(detect_model())

    def _finetune(self,dp,ap,n):
        log=os.path.join(TRAINING_DIR,"finetune.log")
        merged=os.path.join(MODEL_VERSIONS_DIR,f"nex_v{self._state.get('training_count',0)+1}_{int(time.time())}.gguf")
        os.makedirs(MODEL_VERSIONS_DIR,exist_ok=True)
        ap = merged  # output directly to versioned model
        cmd=[FINETUNE_BIN,
             "-m",detect_model(),
             "-f",dp,
             "-o",merged,
             "--learning-rate",str(LORA_CONFIG["learning_rate"]),
             "--epochs",str(LORA_CONFIG["epochs"]),
             "--ctx",str(LORA_CONFIG["max_seq_len"]),
             "--threads",str(LORA_CONFIG["threads"]),
             "--n-gpu-layers",str(LORA_CONFIG["gpu_layers"]),
             "--optimizer","adamw"]
        try:
            r=subprocess.run(cmd,stdout=open(log,"w"),stderr=subprocess.STDOUT,timeout=7200)
            return r.returncode==0 and os.path.exists(ap)
        except Exception as e: logger.error(f"{e}"); return False

    def _merge(self,ap,n):
        mp=detect_model()
        if not mp: return None
        os.makedirs(MODEL_VERSIONS_DIR,exist_ok=True)
        v=self._state.get("training_count",0)+1
        back=os.path.join(MODEL_VERSIONS_DIR,f"nex_base_v{v-1}_{int(time.time())}.gguf")
        merged=os.path.join(MODEL_VERSIONS_DIR,f"nex_v{v}_{int(time.time())}.gguf")
        try: shutil.copy2(mp,back)
        except: pass
        if os.path.exists(EXPORT_BIN):
            r=subprocess.run([EXPORT_BIN,"--model-base",mp,"--lora",ap,"--output",merged],capture_output=True,timeout=1800)
            if r.returncode==0 and os.path.exists(merged): return merged
        return None

    def _restart_server(self,mp):
        if not mp: return
        subprocess.Popen(["llama-server","-m",mp,"--port","8080","-ngl","28","-c","4096"],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

    def _restart_nex(self,mp):
        s=os.path.expanduser("~/.config/nex/restart_lora.sh")
        open(s,"w").write(f"#!/bin/bash\nsleep 2\npkill -9 -f run.py\npkill -9 -f llama-server\nsleep 3\ncd ~/Desktop/nex\nsource venv/bin/activate\nNEX_MODEL='{mp}' nex &\n")
        os.chmod(s,0o755)
        subprocess.Popen(["bash",s],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        time.sleep(2); os.kill(os.getpid(),9)

    def _send(self,chat_id,text):
        if self.bot:
            try: self.bot.send_message(chat_id=chat_id,text=text)
            except Exception as e: logger.warning(f"send failed: {e}")
        else: logger.info(f"[lora] {text[:80]}")

    def status(self):
        c=self._state.get("training_count",0); m=self._state.get("current_model")
        l=self._state.get("last_training_time",0); p="yes" if self._state.get("pending_approval") else "no"
        lines=[f"LoRA sessions: {c}",f"Pending: {p}",f"Model: {os.path.basename(m) if m else 'base (unmodified)'}"]
        if l: lines.append(f"Last: {(time.time()-l)/86400:.1f} days ago")
        if not detect_finetune_bin(): lines.append("⚠ llama-finetune not found")
        return "\n".join(lines)

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    from nex.nex_db import NexDB
    db=NexDB(); t=LoRATrainer(db)
    print("Model:",detect_model())
    print("Finetune:",detect_finetune_bin())
    print(t.status())
