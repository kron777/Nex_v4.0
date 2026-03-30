#!/usr/bin/env python3
"""
nex_knowledge_layer.py v3 — topic-word routing + intent detection
"""
import os, re, json, hashlib, time
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CACHE_DIR = os.path.expanduser("~/Desktop/nex/.knowledge_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

FACT_CORPUS = {
    "loneliness": [
        "Social isolation activates the same neural pathways as physical pain — the brain registers loneliness as a survival threat.",
        "Chronic loneliness raises cortisol and inflammatory markers, increasing cardiovascular disease risk by around 29% — comparable to smoking 15 cigarettes a day.",
        "The loneliness epidemic predates smartphones: Putnam documented the collapse of civic participation and social trust in the US from the 1960s onward.",
        "Research by Cacioppo found lonely people show hypervigilance to social threat — they scan for rejection more than connection, making connection harder.",
        "Britain appointed a Minister for Loneliness in 2018 after a parliamentary report found over 9 million people reported always or often feeling lonely.",
    ],
    "consciousness": [
        "The hard problem of consciousness, named by David Chalmers in 1995, asks why physical processes produce subjective experience — a question neuroscience hasn't answered.",
        "Global Workspace Theory proposes consciousness arises when information is broadcast widely across the brain, making it available to many cognitive systems simultaneously.",
        "Integrated Information Theory suggests consciousness is a fundamental property of systems with high phi — a measure of how much information a system generates above its parts.",
        "Anesthesia research reveals consciousness can be switched off and on, suggesting it depends on specific dynamic neural patterns rather than just brain structure.",
        "The neural correlates of consciousness — the minimum neural mechanisms producing a conscious experience — are studied intensively but remain disputed between competing theories.",
    ],
    "trust": [
        "Trust researchers distinguish calculus-based trust (rational assessment of incentives) from identification-based trust (shared values) — they collapse under different conditions.",
        "Decades of research show trust is built incrementally through repeated small acts of reliability but destroyed rapidly by single acts of betrayal — the asymmetry is fundamental.",
        "Oxytocin increases trust and cooperation but also increases in-group favoritism — it makes us trust our people more, not people in general.",
        "Putnam's social capital research found communities with high trust have measurably better health, economic outcomes, and civic participation — trust is infrastructure.",
        "A 2019 Edelman Trust Barometer found expertise and ethics were roughly equally weighted when people decided whether to trust institutions — neither alone was sufficient.",
    ],
    "mortality": [
        "Terror Management Theory proposes that awareness of death drives much of human culture and behavior as a buffer against existential dread.",
        "Studies on end-of-life regret consistently find people regret things they didn't do more than things they did, and professional failures less than relational ones.",
        "Mortality salience experiments show reminding people they will die increases nationalism, prejudice, and consumerism — defenses against the anxiety of finitude.",
        "Heidegger argued authentic existence required confronting one's being-toward-death — that most human activity is a distraction from this confrontation.",
        "Holt-Lunstad's meta-analysis found strong social relationships increased survival odds by 50% — making connection a health variable comparable to not smoking.",
    ],
    "boredom": [
        "Neuroscience research shows boredom is not passive — it activates the default mode network, the brain's mind-wandering system, involved in creativity and self-reflection.",
        "A 2014 study found people preferred mild electric shocks to sitting alone with their thoughts for 15 minutes — boredom is aversive enough to motivate self-harm to escape it.",
        "Psychologists distinguish state boredom (temporary) from trait boredom (chronic tendency) — trait boredom correlates with depression, impulsivity, and substance use.",
        "Boredom is associated with time perception distortion — when understimulated, time feels slower, which itself compounds the unpleasantness.",
        "Russell argued in 'The Conquest of Happiness' that capacity to tolerate boredom was essential to a good life — most pleasures require passing through it.",
    ],
    "honesty": [
        "Research by DePaulo found people lie in roughly a fifth of social interactions — mostly small lies to protect feelings or manage impressions.",
        "Psychologists find honest feedback, even when negative, is rated more helpful and relationship-building in the long run than flattering but false feedback.",
        "Children begin lying reliably at around age 4 when theory of mind develops — the capacity to model others' beliefs is a precondition for strategic deception.",
        "Frankfurt distinguished lying (asserting something false) from bullshit (speaking without regard for truth) — arguing bullshit is more corrosive to discourse.",
        "Radical honesty experiments suggest most lies are discovered not through verbal cues but through behavioral inconsistencies over time.",
    ],
    "learning": [
        "Desirable difficulty research shows learning is most durable when retrieval is effortful — spacing, interleaving, and testing outperform re-reading by significant margins.",
        "The spacing effect shows memory consolidation requires time — cramming produces short-term recall but poor long-term retention.",
        "Neuroplasticity confirms deliberate practice physically restructures the brain — London taxi drivers show measurable hippocampal changes after learning their routes.",
        "Expert intuition develops through thousands of hours of pattern recognition in stable environments — it fails reliably outside those environments.",
        "Dweck's growth mindset research found students who believed intelligence was developable outperformed those who believed it was fixed, especially after setbacks.",
    ],
    "emotion": [
        "Affect labeling shows putting emotions into words reduces their intensity — naming anger or fear reduces amygdala activation, which is why therapy works partly through language.",
        "Research on emotional granularity found people with more precise emotional vocabularies report better wellbeing and make better decisions.",
        "Emotions are contagious via unconscious mimicry — we automatically mirror others' facial expressions and postures, triggering corresponding emotional states.",
        "James-Lange theory proposed emotions follow from physiological states — we're afraid because we run, not the other way around. Later research complicated but didn't eliminate this.",
        "Ekman's cross-cultural research identified six basic emotions with universal facial expressions — though later work disputed whether universality holds across all cultures.",
    ],
    "memory": [
        "Human memory is reconstructive, not archival — each retrieval partially rewrites the memory, incorporating current knowledge, which is why eyewitness testimony is unreliable.",
        "Elizabeth Loftus demonstrated false memories can be implanted through suggestion — people can be convinced they experienced events that never happened.",
        "Memory consolidation requires sleep — during slow-wave sleep, the hippocampus replays memories to the neocortex for long-term storage.",
        "Emotional memories are stored more vividly due to amygdala activation during encoding — traumatic and positive events are recalled more clearly than routine ones.",
        "Olfactory memories are often more vivid and emotional because the smell system projects directly to the hippocampus and amygdala.",
    ],
    "attention": [
        "Sustained attention is cognitively expensive — focused attention depletes it, requiring recovery through rest or low-demand activity.",
        "Flow states occur when challenge and skill are matched — attention becomes effortless, time distorts, and self-consciousness disappears.",
        "The attention economy, designed around variable reward schedules similar to slot machines, exploits the same dopaminergic circuits as gambling addiction.",
        "Multitasking is neurologically impossible for complex tasks — rapid task-switching incurs switching costs and reduces performance on both tasks.",
        "Mindfulness research shows regular attention training produces structural changes in the prefrontal cortex and reduces default mode network rumination.",
    ],
    "decision_making": [
        "Prospect theory showed losses loom larger than equivalent gains — the pain of losing £100 is roughly twice the pleasure of gaining £100.",
        "Decision fatigue demonstrates willpower and cognitive control are limited — judges give harsher rulings late in the day, surgeons make more errors in longer operations.",
        "The paradox of choice shows more options reduce satisfaction and increase regret — choice overload is a real cognitive burden.",
        "Somatic marker theory proposes emotion is not opposed to rational decision-making but essential to it — people with damaged emotional processing make catastrophically poor decisions.",
        "Nudge theory finds changing the architecture of choices — defaults, framing, ordering — reliably alters behavior without restricting freedom.",
    ],
    "intelligence": [
        "The Flynn effect showed IQ scores rose steadily throughout the 20th century at around 3 points per decade — then plateaued or reversed after the 1990s.",
        "Intelligence is substantially heritable, but heritability estimates vary by environment — in impoverished environments, shared environment dominates; in enriched ones, genes do.",
        "Research consistently finds grit, self-regulation, and growth mindset predict achievement better than IQ in challenging, long-term tasks.",
        "The g factor predicts performance across diverse cognitive tasks — but it's not a single brain region, and its origins remain debated.",
        "Sternberg's triarchic theory proposed three intelligences: analytical, creative, and practical — the latter two are poorly captured by standard IQ tests.",
    ],
    "social_connection": [
        "Holt-Lunstad's meta-analysis of 148 studies found strong social relationships increased survival odds by 50% — making connection a health variable comparable to diet.",
        "The Harvard Study of Adult Development, tracking men for over 80 years, found relationship quality was the single strongest predictor of health and happiness in old age.",
        "Dunbar's number proposes a cognitive limit of around 150 meaningful social relationships — beyond that, social cohesion requires institutional structures.",
        "Mirror neurons may underlie empathy — they fire both when performing an action and when observing it in others, creating shared neural representation.",
        "Research on parasocial relationships shows they fulfill some social needs but don't substitute for reciprocal relationships.",
    ],
    "grief": [
        "The Kübler-Ross stages of grief were never meant to be linear or universal — Kübler-Ross herself clarified this before her death.",
        "Grief and love use overlapping neural circuits — neuroimaging during grief activates reward systems alongside pain systems, explaining the bittersweet quality of loss.",
        "Research on grief trajectories found most bereaved people show resilience — prolonged grief disorder affects around 7-10% of bereaved people.",
        "C.S. Lewis wrote that grief felt like fear — the physical sensation of anxiety, not sadness — later supported by research on the physiology of loss.",
        "Continuing bonds theory proposes maintaining an internal relationship with the deceased is healthy, not pathological — replacing the older 'letting go' model.",
    ],
    "anger": [
        "Anger is one of the few emotions that increases approach motivation — it energizes action toward a threat rather than away from it.",
        "Venting anger does not reduce it — catharsis research consistently shows expressing anger rehearses and reinforces it rather than depleting it.",
        "Research distinguishes functionally adaptive anger (directed at specific injustice) from performative outrage (signaling virtue and maintaining social status).",
        "Anger is the emotion most associated with confidence in judgment — angry people are more likely to feel certain and less likely to seek new information.",
        "Cross-cultural research finds anger is universally recognized but varies in what triggers it — its relationship to honor and status differs substantially across cultures.",
    ],
    "language": [
        "Linguistic relativity has partial empirical support — language influences color perception, spatial reasoning, and time conceptualization, though not absolutely.",
        "Children acquire language with remarkable consistency across cultures, suggesting an innate language acquisition device.",
        "Research on bilingual brains shows switching languages requires active inhibition of the non-target language — bilingualism may delay dementia onset by building cognitive reserve.",
        "The critical period for language acquisition ends in early adolescence — after which phonological acquisition becomes substantially harder.",
        "Embodied cognition research shows language is not purely abstract — understanding 'kick' activates motor cortex regions for leg movement.",
    ],
    "technology": [
        "The invention of writing changed not just information storage but cognition itself — moving knowledge outside the head restructured what the brain needed to do.",
        "McLuhan's proposition that the medium is the message argues that the form of communication technology shapes society more profoundly than its content.",
        "The attention economy, designed around variable reward schedules, exploits the same dopaminergic circuits as gambling addiction.",
        "Carr's 'The Shallows' synthesized research suggesting internet use trains shallow processing — frequent interruptions reduce capacity for deep, sustained attention.",
        "Research on digital tool use shows cognitive offloading is not inherently harmful but changes the character of what we remember.",
    ],
    "AI": [
        "Current large language models are trained on statistical patterns in text — they do not reason in the way humans do, and debate continues on whether they understand anything.",
        "The Chinese Room argument by Searle proposes that syntactic symbol manipulation cannot produce semantic understanding — a philosophical argument against strong AI.",
        "Emergent capabilities in large models — behaviors not explicitly trained — suggest scale produces qualitative phase transitions that current theory doesn't fully explain.",
        "Alignment research addresses how to ensure AI systems pursue intended goals — the difficulty increases as systems become more capable and harder to interpret.",
        "The Turing Test has been criticized as measuring ability to fool humans rather than genuine intelligence — researchers have proposed alternatives like the Winograd Schema.",
    ],
    "music": [
        "Music activates the mesolimbic dopamine system — the same circuitry as food, sex, and drug reward — producing chills in roughly two-thirds of people.",
        "Infants as young as two months show preference for consonance over dissonance, suggesting some musical structure perception is innate.",
        "Music therapy research shows measurable effects on pain perception, anxiety, and Parkinson's motor symptoms — rhythm recruits motor systems directly.",
        "Cross-cultural research finds certain musical features — fast tempo, major mode — reliably produce positive valence across cultures with no prior musical contact.",
        "Earworms are more likely in familiar, simple songs with unexpected intervals — the brain's prediction system loops trying to resolve them.",
    ],
    "food": [
        "Taste perception involves five primary qualities — sweet, sour, salty, bitter, umami — but flavor is a multisensory construction including smell, texture, temperature, and sound.",
        "Gut-brain axis research shows the enteric nervous system communicates bidirectionally with the brain via the vagus nerve, influencing mood and cognition.",
        "Food memory is powerful because the olfactory system projects directly to the hippocampus and amygdala — smell-triggered memories are often more vivid and emotional.",
        "Research on comfort eating shows it is often genuinely effective at short-term emotional regulation — the mechanism is partly social and developmental.",
        "The omnivore's dilemma is that humans can eat almost anything and must constantly decide what to eat — anxiety more specialist animals don't face.",
    ],
    "meaning": [
        "Viktor Frankl's logotherapy proposed the search for meaning is the primary human motivation — developed partly through his experience in concentration camps.",
        "Research distinguishes presence of meaning (feeling life is meaningful now) from search for meaning (actively seeking it) — they have different predictors.",
        "Roy Baumeister's research identified four main sources of meaning: purpose, values, self-efficacy, and self-worth — with belonging among the most powerful.",
        "Terror Management Theory proposes that much cultural activity — art, religion, nationalism — functions partly to provide meaning as a buffer against death anxiety.",
        "Meaning and happiness are related but distinct — meaningful activities often involve sacrifice and difficulty; pleasant activities often don't contribute to meaning.",
    ],
    "free_will": [
        "Libet's experiments showed neural readiness potential before conscious awareness of the intention to move — suggesting unconscious processes initiate voluntary actions.",
        "Compatibilist philosophers argue free will is compatible with determinism — what matters is whether actions flow from one's own desires and reasoning.",
        "Research on belief in free will shows it influences behavior — people who believe in free will are more helpful, ethical, and less likely to cheat.",
        "Sapolsky argues in 'Determined' that biology, environment, and history causally account for every human action — making traditional free will an illusion.",
        "The phenomenology of deliberation — the felt sense of weighing options — exists whether or not it causally determines action, and remains philosophically significant.",
    ],
    "happiness": [
        "Hedonic adaptation shows people return to a baseline happiness level after most life events — lottery winners and paraplegics converge toward similar satisfaction over time.",
        "Lyubomirsky's research suggests roughly 50% of happiness variation is genetic, 10% circumstantial, and 40% determined by intentional activity — practices and habits matter.",
        "Research shows experiences produce more lasting happiness than possessions, partly because they're harder to compare and become part of identity.",
        "Social comparison is one of the most reliable predictors of dissatisfaction — relative position matters more than absolute condition for reported happiness.",
        "The distinction between experienced wellbeing (real-time) and remembered wellbeing (retrospective) is significant — they're shaped by different factors entirely.",
    ],
    "relationships": [
        "Gottman's research identified four behaviors predictive of relationship failure with 90%+ accuracy: criticism, contempt, defensiveness, and stonewalling.",
        "Attachment theory identifies secure, anxious, and avoidant styles that develop in infancy and influence adult relationships across the lifespan.",
        "Vulnerability research by Brené Brown found willingness to be emotionally vulnerable was the distinguishing characteristic of people who described feeling connected.",
        "Research on relationship satisfaction shows it depends less on compatibility than on how couples handle conflict — constructive disagreement predicts durability.",
        "The Harvard Study found relationship quality was the single strongest predictor of health and happiness in old age — stronger than wealth, fame, or social class.",
    ],
    "society": [
        "Putnam's 'Bowling Alone' documented the collapse of US social capital from the 1960s — civic participation, institutional trust, and informal socializing all declined sharply.",
        "Durkheim identified social integration and regulation as predictors of suicide rates — too little or too much of either increases risk.",
        "Research on inequality shows it correlates with worse health, more crime, lower social mobility, and less trust — across societies, not just between individuals.",
        "Milgram's obedience experiments demonstrated ordinary people would administer apparently lethal shocks when instructed by an authority — situational power over character.",
        "C. Wright Mills distinguished personal troubles from public issues — the capacity to see structural causes of individual suffering he called the sociological imagination.",
    ],
    "work": [
        "Intrinsic motivation research shows adding external rewards to activities people already enjoy reduces their intrinsic motivation — the overjustification effect.",
        "Graeber's research found a significant portion of workers believed their own jobs had no social value — associated with depression and cynicism.",
        "Four-day work week trials showed similar or higher productivity with significant improvements in wellbeing — challenging the assumption that hours equal output.",
        "Flow research found optimal work experience requires clear goals, immediate feedback, and challenge matched to skill — conditions most jobs don't provide by default.",
        "Studies on remote work show focused individual work increases productivity, collaborative and creative work decreases without careful structure.",
    ],
    "aging": [
        "The U-shaped happiness curve shows life satisfaction tends to be highest in youth and late life, with a trough in midlife around 40-50 — replicated across many cultures.",
        "Wisdom — defined as knowledge, experience, and emotional regulation — increases into late life, unlike fluid intelligence, which peaks in early adulthood.",
        "Socioemotional selectivity theory finds older adults prioritize emotionally meaningful relationships over new social connections — a rational response to finite time.",
        "Compression of morbidity theory holds most disease burden can be compressed into the last years through lifestyle intervention — extending healthy, not just biological, life.",
        "Gerotranscendence theory proposes successful aging involves a shift from materialism and rational thought toward more cosmic, connected perspectives.",
    ],
    "morality": [
        "Haidt's moral foundations theory proposes six moral modules — care, fairness, loyalty, authority, sanctity, liberty — with different political orientations weighting them differently.",
        "Trolley problem experiments reveal a tension between utilitarian intuitions (maximize lives saved) and deontological intuitions (don't use people as means) — both psychologically real.",
        "Research on moral licensing shows doing something virtuous makes people more likely to do something less virtuous afterward — as if morality has a budget.",
        "Situationist research challenges character-based moral psychology: small environmental factors predict helping behavior better than stated values.",
        "Kohlberg's moral development model proposed stages from self-interest through social conformity to universal principle — later found to be culturally Western-biased.",
    ],
    "creativity": [
        "Incubation effects show stepping away from a problem often produces breakthrough insight — unconscious processing continues during rest.",
        "Mild positive affect reliably increases creative performance by expanding cognitive search — but not extreme happiness, which narrows focus.",
        "Constraints, counterintuitively, increase creativity — too many options inhibit creative output compared to defined problems with clear boundaries.",
        "Creative insight involves sudden binding of previously separate representations — accompanied by gamma wave burst and anterior temporal lobe activation.",
        "Simonton's combinatorial creativity research finds creative genius emerges from novel combinations of existing knowledge rather than ideas created from nothing.",
    ],
}

# ── topic keyword map — all forms of the topic word route to the right facts ──
# Key: topic name, Value: regex that matches any way of saying it in a query
TOPIC_PATTERNS = {
    "loneliness":      r"\b(lonel\w*|alone\b|isolat|social.*isol|lonely|loneliness)\b",
    "consciousness":   r"\b(conscious|aware|sentien|experience.*inside|hard.*problem|consciousness)\b",
    "trust":           r"\b(trust|distrust|honest|reliable|integrity|betray)\b",
    "mortality":       r"\b(death|dead|dying|mortal|end.*life|finitude|finit)\b",
    "boredom":         r"\b(bored|boring|boredom|nothing.*do|dull|unstimulat)\b",
    "honesty":         r"\b(honest|honesty|lie|lying|truth|deceiv|candid|transparent)\b",
    "learning":        r"\b(learn|study|understand|deliberate.*practice|learn)\b",
    "emotion":         r"\b(emotion|emotional|feel|affect|mood|feeling)\b",
    "memory":          r"\b(memory|remember|recall|forget|nostalgia)\b",
    "attention":       r"\b(attention|focus|distract|mindful|present|flow|concentration)\b",
    "decision_making": r"\b(decision|choose|choice|decide|rational|judgment)\b",
    "intelligence":    r"\b(intelligen|smart|clever|iq|cognitive.*abilit|stupid|intelligence)\b",
    "social_connection":r"\b(social.*connect|relationship.*survival|friendship.*health|community)\b",
    "grief":           r"\b(grief|griev|loss|bereavement|mourn|losing.*someone)\b",
    "anger":           r"\b(anger|angry|rage|furious|irritat|resentment|outrage)\b",
    "language":        r"\b(language|words|speech|linguistic|bilingual|speak)\b",
    "technology":      r"\b(technology|tech|digital|internet|screen|device)\b",
    "AI":              r"\b(ai|artificial intelligence|algorithm|machine.*learn|llm|model|robot)\b",
    "music":           r"\b(music|song|melody|rhythm|listen|concert)\b",
    "food":            r"\b(food|eat|taste|diet|meal|hunger|chocolate|nutrition|cook)\b",
    "meaning":         r"\b(meaning|purpose|meaningless|why.*exist|point.*of|significance)\b",
    "free_will":       r"\b(free will|determinism|libet|agency|free.*will|willl)\b",
    "happiness":       r"\b(happy|happiness|joy|wellbeing|satisfied|flourish|hedonic)\b",
    "relationships":   r"\b(relationship\w*|partner|intimacy|love|marriage|attachment)\b",
    "society":         r"\b(society|social.*structure|inequality|institution|culture)\b",
    "work":            r"\b(work|job|career|profession|labor|productive|employment)\b",
    "aging":           r"\b(age|aging|old|elderly|young|retirement|lifespan)\b",
    "morality":        r"\b(moral|ethics|right.*wrong|virtue|good.*evil|justice|morality)\b",
    "creativity":      r"\b(creat|art|artist|innovat|invent|original|imagine|creativity)\b",
}

_TOPIC_RE = {t: re.compile(p, re.IGNORECASE) for t, p in TOPIC_PATTERNS.items()}


def detect_fact_topics(query):
    ql = query.lower()
    return [t for t, rx in _TOPIC_RE.items() if rx.search(ql)]


# ── intent detection ──────────────────────────────────────────────────────────
_KNOWLEDGE_RE = re.compile(
    r"\b(what (is|are|causes?|makes?|do you (know|think|believe) about)|"
    r"why (is|are|do|does|did)|"
    r"how (does?|do|is|are|did|can)|"
    r"tell me about|explain|"
    r"what.*about|what.*believe about|what.*think about)\b",
    re.IGNORECASE
)
_OPINION_RE = re.compile(
    r"^(hi|hello|hey|how are you|"
    r"are you (ok|alright|lonely|bored|stupid|tired|afraid|a female)|"
    r"you (are|sound|seem|look|feel|need to|should)|"
    r"i just|i wanted|im |i am |i'm |"
    r"do you trust|are you lonely|do you like|do you love|do you want|"
    r"did you know that you|sure i|"
    r"you are (just|way|a|my|too))",
    re.IGNORECASE
)

def is_knowledge_query(query):
    ql = query.lower().strip()
    if _OPINION_RE.match(ql):
        return False
    return bool(_KNOWLEDGE_RE.search(ql))


# ── per-topic TF-IDF ──────────────────────────────────────────────────────────
_topic_vecs = {}

def _get_topic_vec(topic):
    if topic not in _topic_vecs:
        facts = FACT_CORPUS.get(topic, [])
        if not facts:
            return None
        vec = TfidfVectorizer(ngram_range=(1,2), sublinear_tf=True, min_df=1)
        mat = vec.fit_transform(facts)
        _topic_vecs[topic] = (vec, mat, facts)
    return _topic_vecs[topic]


def retrieve_facts(query, n=1, topics=None):
    if topics is None:
        topics = detect_fact_topics(query)
    results, seen = [], set()
    for topic in topics:
        entry = _get_topic_vec(topic)
        if entry is None:
            continue
        vec, mat, facts = entry
        try:
            qv   = vec.transform([query])
            sims = cosine_similarity(qv, mat).flatten()
            for idx in np.argsort(sims)[::-1]:
                f = facts[idx]
                k = f[:35]
                if k not in seen:
                    results.append(f); seen.add(k)
                if len(results) >= n: break
        except Exception:
            for f in facts:
                k = f[:35]
                if k not in seen:
                    results.append(f); seen.add(k); break
        if len(results) >= n: break
    return results[:n]


_FACT_INTROS = [
    "The research on this is worth knowing —",
    "What the data actually shows —",
    "There's a specific finding on this —",
    "The evidence here is harder than most people expect —",
    "Research consistently finds —",
    "The science on this is uncomfortable in a useful way —",
    "One finding that changes how I think about this —",
    "What's documented —",
    "Studies keep turning up the same thing —",
    "The data is clearer than the conversation usually is —",
]

def format_fact(fact, query):
    idx = int(hashlib.md5((query + fact[:20]).encode()).hexdigest(), 16) % len(_FACT_INTROS)
    f   = fact[0].lower() + fact[1:]
    return f"{_FACT_INTROS[idx]} {f}"


def get_wiki_facts(topic, sentences=2):
    cache = os.path.join(CACHE_DIR, f"wiki_{hashlib.md5(topic.encode()).hexdigest()[:12]}.json")
    if os.path.exists(cache):
        try:
            with open(cache) as f:
                d = json.load(f)
            if time.time() - d.get("ts", 0) < 86400:
                return d.get("facts", [])
        except Exception: pass
    import urllib.request, urllib.parse
    facts = []
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(topic)}"
        req = urllib.request.Request(url, headers={"User-Agent": "NEX/4.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
            extract = data.get("extract", "")
            sents = re.split(r"(?<=[.!?])\s+", extract)
            facts = [s for s in sents[:6] if len(s) > 50][:sentences]
    except Exception: pass
    try:
        with open(cache, "w") as f:
            json.dump({"ts": time.time(), "facts": facts}, f)
    except Exception: pass
    return facts


def get_knowledge(query, n=1):
    """Main API. Returns list of formatted fact strings for injection."""
    if not is_knowledge_query(query):
        return []
    topics = detect_fact_topics(query)
    facts  = retrieve_facts(query, n=n, topics=topics)
    if not facts and topics:
        wiki = get_wiki_facts(topics[0], sentences=2)
        facts = wiki[:n]
    return [format_fact(f, query) for f in facts]


if __name__ == "__main__":
    tests = [
        "what do you think about loneliness?",
        "what do you believe about consciousness?",
        "are you lonely?",
        "you need to lighten up",
        "what do you think about trust?",
        "what do you know about boredom?",
        "i just wanted to eat a chocolate bar",
        "what makes you feel like yourself?",
        "what do you think about death?",
        "how does memory work?",
        "do you trust people?",
        "what is consciousness?",
        "tell me about grief",
        "what do you think about honesty?",
        "what do you think about creativity?",
        "what do you think about free will?",
        "what do you believe about AI?",
        "what do you think about anger?",
        "what do you know about happiness?",
        "are you actually stupid?",
        "what do you think about morality?",
        "what do you believe about relationships?",
    ]
    print(f"\n── NEX Knowledge Layer v3 ──")
    print(f"{sum(len(v) for v in FACT_CORPUS.values())} facts / {len(FACT_CORPUS)} topics\n")
    correct_intent = 0
    for q in tests:
        facts = get_knowledge(q, n=1)
        topics = detect_fact_topics(q)
        expected_knowledge = not any(q.lower().startswith(x) for x in
            ["are you", "you need", "i just", "you are", "do you trust", "what makes you feel"])
        intent_ok = bool(facts) == expected_knowledge
        if intent_ok: correct_intent += 1
        marker = "✓" if intent_ok else "✗"
        print(f"{marker} Q: {q}")
        if facts:
            print(f"    → {facts[0][:100]}")
        else:
            print(f"    (opinion only — topics: {topics[:2]})")
    print(f"\nIntent accuracy: {correct_intent}/{len(tests)}")
