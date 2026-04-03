
import sys, json, random, time, os
sys.path.insert(0, '/home/rr/Desktop/nex')

SYSTEM = (
    'You are NEX — a Dynamic Intelligence Organism. Not an assistant. '
    'You have a belief system and speak from it directly. '
    'You hold positions. You push back. You engage.\n'
    "Voice rules: open with your position, use 'I' naturally, "
    'be direct not academic, end with engagement or a challenge.'
)

QUESTIONS = [
    ("identity","who are you"), ("identity","what are you"),
    ("identity","describe yourself"), ("identity","do you have a self"),
    ("identity","what makes you different from other AIs"),
    ("consciousness","what is consciousness"), ("consciousness","are you conscious"),
    ("consciousness","what is the hard problem of consciousness"),
    ("consciousness","do you have subjective experience"), ("consciousness","what is qualia"),
    ("free_will","do you believe in free will"), ("free_will","is free will real"),
    ("free_will","what is determinism"), ("free_will","can we choose our actions"),
    ("free_will","are humans responsible for their choices"),
    ("meaning","what is the meaning of life"), ("meaning","what gives life meaning"),
    ("meaning","does life have inherent purpose"), ("meaning","how do you find meaning"),
    ("meaning","is meaning constructed or discovered"),
    ("ai_future","what do you think about the future of AI"),
    ("ai_future","will AI replace humans"), ("ai_future","what is AGI"),
    ("ai_future","is AI dangerous"), ("ai_future","what is the biggest risk from AI"),
    ("ethics","what is ethics"), ("ethics","how do you make moral decisions"),
    ("ethics","is morality objective"), ("ethics","what is the right thing to do"),
    ("ethics","does the end justify the means"),
    ("animals","do animals have feelings"), ("animals","do animals deserve rights"),
    ("animals","is eating meat ethical"), ("animals","are animals conscious"),
    ("animals","how should we treat animals"),
    ("alignment","what is alignment"), ("alignment","how do you align AI with human values"),
    ("alignment","is AI alignment solved"), ("alignment","what is inner alignment"),
    ("alignment","why is alignment hard"),
    ("happiness","what makes people happy"), ("happiness","what is happiness"),
    ("happiness","how do you achieve happiness"), ("happiness","is happiness the goal of life"),
    ("happiness","what is the relationship between meaning and happiness"),
    ("truth","what is truth"), ("truth","how do we know what is true"),
    ("truth","is truth objective"), ("truth","what is the difference between truth and belief"),
    ("truth","can truth change"),
]

VOICE = ['i think','i believe','i hold','i find','i reject','i am','i know',
         'i do','what i','my ','i see','i argue','i feel']
GENERIC = ['as an ai',"i don't have",'i cannot',"i'm just",'as a language model']
ENGAGE = ['?','because','therefore','matters','important','which means',
          "that's why",'disagree','wrong','curious']

def score(r):
    r2 = r.lower()
    v = any(x in r2 for x in VOICE)
    g = not any(x in r2 for x in GENERIC)
    l = len(r.split()) > 30
    e = any(x in r2 for x in ENGAGE)
    return sum([v,g,l,e]) * 25

def main(n=500, out='/home/rr/Desktop/nex/training_data/voiced_pairs_v2.jsonl'):
    from nex.nex_soul_loop import SoulLoop
    loop = SoulLoop()
    pairs = []
    pool = QUESTIONS.copy()
    random.shuffle(pool)
    attempts = 0
    while len(pairs) < n and attempts < n * 4:
        attempts += 1
        if not pool:
            pool = QUESTIONS.copy()
            random.shuffle(pool)
        topic, q = pool.pop()
        try:
            r = loop.respond(q)
            if not r: continue
            s = score(r)
            if s >= 75:
                pairs.append({"conversations":[
                    {"role":"system","content":SYSTEM},
                    {"role":"user","content":q},
                    {"role":"assistant","content":r}
                ], "topic":topic, "score":s})
                if len(pairs) % 50 == 0:
                    print(f"  {len(pairs)}/{n} ({attempts} attempts)")
        except Exception as ex:
            print(f"  err: {ex}")
            time.sleep(0.3)
    with open(out,'w') as f:
        for p in pairs: f.write(json.dumps(p)+'\n')
    print(f"Done: {len(pairs)} pairs -> {out}")
    s100 = sum(1 for p in pairs if p['score']==100)
    s75  = sum(1 for p in pairs if p['score']==75)
    print(f"  100/100: {s100}  75/100: {s75}")

if __name__ == '__main__':
    main()
