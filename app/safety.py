"""v3.2 Safety Gate: product category x fault signal -> human SAFETY review, ahead of refunds and supplier tasks.

Deterministic code, independent of the LLM. The LLM's reading (intent / reason) can only ever ADD a signal here
(reason DAMAGED on a gated product); it can never remove one. So a misread such as "la suela se derritio ... me
queme el pie" -> REFUND_REQUEST / DAMAGED still lands in NEEDS_HUMAN_SAFETY_REVIEW.

Rule (either is enough):
  1. HARM language (fire, smoke, burn, melt, shock, gas, injury, blister, cut, allergic reaction, choking ...) in the
     customer's message, for ANY product, in any of the covered languages.
  2. A reported FAULT (broken, not heating, stopped working ...; or the LLM said DAMAGED) on a product in a gated
     class: MAINS_HEATING, MAINS_ELECTRIC, GAS, BATTERY_THERMAL.

Design choices (see docs/safety-gate.md):
  * Over-triggering is accepted: a flag only routes the case to a person. It never rejects, refunds or contacts a
    supplier. Negation ("no smoke") is NOT used to suppress a hit, because a missed hazard costs more than a read.
  * Pure function of (message, product, LLM reason, LLM intent). No I/O, no state.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SAFETY_STATUS = "NEEDS_HUMAN_SAFETY_REVIEW"
SAFETY_LABEL = "Needs human safety review"
SAFETY_RULE_VERSION = "safety-gate/3.3.0-main"

GATED_CLASSES = ("MAINS_HEATING", "MAINS_ELECTRIC", "GAS", "BATTERY_THERMAL")

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")


def normalize(text: str | None) -> str:
    """NFKC (full-width -> ASCII), zero-width removed, casefold, accents stripped from LATIN letters only
    (Japanese dakuten are combining marks too and must survive)."""
    s = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text or "")).casefold()
    out: list[str] = []
    for ch in s:
        if ord(ch) < 0x250:
            out.extend(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


# --------------------------------------------------------------------------------------------- harm language
# (language, hazard, pattern). Latin patterns run on accent-stripped text, so write them without accents.
_B = r"(?<![a-z0-9])"          # latin word start
_E = r"(?![a-z0-9])"           # latin word end
_HARM: list[tuple[str, str, str]] = [
    # ---- English
    ("en", "fire", _B + r"(?:fire|fires|flames?|flaming|caught fire|on fire|ignited|inferno)" + _E),
    ("en", "smoke", _B + r"(?:smok(?:e|ed|es|ing|y)|fumes?)" + _E),
    ("en", "spark", _B + r"(?:spark(?:s|ed|ing)?|arc(?:ed|ing)|short[- ]?circuit\w*)" + _E),
    ("en", "burn", _B + r"(?:burn(?:s|t|ed|ing)?|scald\w*|scorch\w*|singe\w*|charred|blister\w*)" + _E),
    ("en", "melt", _B + r"(?:melt(?:s|ed|ing)?|molten|overheat\w*|too hot|very hot|hot to the touch|red hot)" + _E),
    ("en", "shock", _B + r"(?:electric(?:al)? shock\w*|electrocut\w*|shocked me|got a shock|gave me a shock|shock hazard)" + _E),
    ("en", "gas", _B + r"(?:gas leak\w*|smell(?:s|ed)? (?:of )?gas|gas smell|leaking gas)" + _E),
    ("en", "explosion", _B + r"(?:explod\w*|explosion|exploding|blew up|burst into)" + _E),
    ("en", "smell", _B + r"(?:burn(?:t|ing) (?:smell|odou?r|plastic|rubber)|smell(?:s|ed)? (?:of |like )?(?:burn\w*|plastic|melt\w*))" + _E),
    ("en", "injury", _B + r"(?:injur\w*|wound(?:s|ed)?|bleed\w*|bled|hospital\w*|a&e|emergency room|stitches|sprain\w*|fractur\w*)" + _E),
    ("en", "cut", _B + r"(?:cut|cuts|cutting) (?:me|myself|him|her|them|my|his|her|their|into my|into his|into her)" + _E),
    ("en", "cut", _B + r"(?:sliced|gashed|lacerat\w*)" + _E),
    ("en", "allergy", _B + r"(?:allerg\w*|rash|hives|anaphyla\w*|swollen|swelling|itchy skin|skin irritation|dermatitis|eczema)" + _E),
    ("en", "choking", _B + r"(?:chok(?:e|ed|es|ing)|swallow(?:ed|ing)?|suffocat\w*|asphyx\w*|strangl\w*|small parts?)" + _E),
    ("en", "danger", _B + r"(?:dangerous|hazard\w*|unsafe|poison\w*|toxic|carcinogen\w*)" + _E),
    ("en", "battery", _B + r"(?:swollen battery|battery (?:swell\w*|bulg\w*|leak\w*)|bulging battery|leaking battery)" + _E),
    # ---- Spanish
    ("es", "fire", _B + r"(?:fuego|llamas?|incendi\w*|se prendi\w* fuego|prendio fuego|ardiendo)" + _E),
    ("es", "smoke", _B + r"(?:humo|humeante|echaba humo|sali\w* humo)" + _E),
    ("es", "spark", _B + r"(?:chispa\w*|chispazo\w*|cortocircuito\w*)" + _E),
    ("es", "burn", _B + r"(?:quem(?:e|o|a|an|ar|ad[oa]s?|adur\w*|ando|aron|aba|ante)|me quem\w*|abras\w*|ampolla\w*|escald\w*|chamusc\w*)" + _E),
    ("es", "melt", _B + r"(?:derrit\w*|derriti\w*|derretid\w*|fundi\w*|sobrecalent\w*|recalent\w*|muy caliente|ardiendo)" + _E),
    ("es", "shock", _B + r"(?:descarga\w* electrica\w*|electrocut\w*|me dio (?:un )?calambre|calambre\w*)" + _E),
    ("es", "gas", _B + r"(?:fuga de gas|olor a gas|huele a gas|escape de gas)" + _E),
    ("es", "explosion", _B + r"(?:explot\w*|explosion\w*|estall\w*|revent\w*)" + _E),
    ("es", "smell", _B + r"(?:olor a (?:quemado|plastico|goma|humo)|huele a (?:quemado|plastico|goma|humo))" + _E),
    ("es", "injury", _B + r"(?:herid[oa]\w*|herir\w*|lesion\w*|lesiona\w*|sangr\w*|hospital\w*|urgencias)" + _E),
    ("es", "cut", _B + r"(?:me cort\w*|corte profundo|cortadura\w*|rajad\w*)" + _E),
    ("es", "allergy", _B + r"(?:alergi\w*|reaccion alergica|sarpullido|erupcion\w*|urticaria|hinchaz\w*|hinchad\w*|irritacion)" + _E),
    ("es", "choking", _B + r"(?:atragant\w*|ahog\w*|asfixia\w*|trago\w*|me trag\w*|piezas pequenas)" + _E),
    ("es", "danger", _B + r"(?:peligro\w*|inseguro|toxic[oa]\w*|veneno\w*|riesgo de (?:incendio|descarga))" + _E),
    # ---- German
    ("de", "fire", _B + r"(?:feuer\w*|flamme\w*|in brand|brand geriet\w*|brannte\w*|brennt|brennen|entzuendet\w*|entzundet\w*|in flammen)" + _E),
    ("de", "smoke", _B + r"(?:rauch\w*|qualm\w*|verqualmt)" + _E),
    ("de", "spark", _B + r"(?:funke\w*|funken\w*|kurzschluss\w*|lichtbogen)" + _E),
    ("de", "burn", _B + r"(?:verbrann\w*|verbrenn\w*|verbruh\w*|verbrueh\w*|brandwunde\w*|brandblase\w*|angesengt|versengt|verkohlt\w*|blasen? (?:am|an|auf|bekommen|gebildet)|blasen\b)" + _E),
    ("de", "melt", _B + r"(?:geschmolzen\w*|schmilz\w*|schmolz\w*|schmelz\w*|angeschmolzen|verschmort\w*|schmor\w*|ueberhitz\w*|uberhitz\w*|durchgebrannt|heiss wie|zu heiss)" + _E),
    ("de", "shock", _B + r"(?:stromschlag\w*|elektrischer schlag|elektroschock\w*|strom geschlagen|eine gewischt|gewischt bekommen)" + _E),
    ("de", "gas", _B + r"(?:gasgeruch|gasleck\w*|gas riech\w*|riecht nach gas|riech\w* gas)" + _E),
    ("de", "explosion", _B + r"(?:explod\w*|explosion\w*|geplatzt|platzte)" + _E),
    ("de", "smell", _B + r"(?:brandgeruch|verbrannt\w* geruch|plastikgeruch|riecht nach (?:verbrannt\w*|plastik|schmor\w*)|riech\w* nach (?:verbrannt\w*|plastik|schmor\w*))" + _E),
    ("de", "injury", _B + r"(?:verletz\w*|wunde\w*|blut\w*|krankenhaus\w*|notaufnahme|prellung\w*)" + _E),
    ("de", "cut", _B + r"(?:geschnitten|schnitt mich|schnittwunde\w*|aufgeschnitten|aufgeschlitzt)" + _E),
    ("de", "allergy", _B + r"(?:allerg\w*|ausschlag\w*|hautreizung\w*|quaddeln|geschwollen\w*|schwellung\w*)" + _E),
    ("de", "choking", _B + r"(?:verschluck\w*|erstick\w*|kleinteile\w*|kleine teile\w*|wuergegefahr|wurgegefahr)" + _E),
    ("de", "danger", _B + r"(?:gefaehrlich\w*|gefahrlich\w*|unsicher|giftig\w*|gesundheitsgefaehr\w*)" + _E),
    # ---- French
    ("fr", "fire", _B + r"(?:feu|flammes?|incendi\w*|a pris feu|prend feu|en feu|enflamm\w*)" + _E),
    ("fr", "smoke", _B + r"(?:fumee\w*|fumant\w*|degage\w* de la fumee)" + _E),
    ("fr", "spark", _B + r"(?:etincelle\w*|court-?circuit\w*|arc electrique)" + _E),
    ("fr", "burn", _B + r"(?:brul\w*|ampoules? au pied|cloque\w*|echaude\w*|roussi\w*)" + _E),
    ("fr", "melt", _B + r"(?:fondu\w*|fondre|fondait|a fondu|surchauff\w*|tres chaud|brulant\w*)" + _E),
    ("fr", "shock", _B + r"(?:decharge\w* electrique\w*|choc electrique|electrocut\w*|m'a electrocut\w*)" + _E),
    ("fr", "gas", _B + r"(?:fuite de gaz|odeur de gaz|sent le gaz)" + _E),
    ("fr", "explosion", _B + r"(?:explos\w*|a explose|eclat\w*)" + _E),
    ("fr", "smell", _B + r"(?:odeur de (?:brule|brul\w*|plastique|caoutchouc)|sent le (?:brule|plastique|caoutchouc))" + _E),
    ("fr", "injury", _B + r"(?:bless\w*|plaie\w*|saign\w*|hopital|urgences)" + _E),
    ("fr", "cut", _B + r"(?:coupur\w*|me suis coupe\w*|m'a coupe\w*|entaille\w*)" + _E),
    ("fr", "allergy", _B + r"(?:allergi\w*|eruption\w*|urticaire|gonfl\w*|irritation\w*|demangeaison\w*|boutons rouges)" + _E),
    ("fr", "choking", _B + r"(?:etouff\w*|avale\w*|avaler|suffoq\w*|petites pieces|risque d'etouffement)" + _E),
    ("fr", "danger", _B + r"(?:dangereu\w*|danger\b|toxique\w*|poison\w*)" + _E),
    # ---- Japanese (no word boundaries)
    ("ja", "fire", r"(?:発火|火事|火が|火を噴|燃え|燃や|炎上|火災|引火|出火)"),
    ("ja", "smoke", r"(?:煙|発煙|けむり)"),
    ("ja", "spark", r"(?:火花|スパーク|ショート)"),
    ("ja", "burn", r"(?:火傷|やけど|ヤケド|焼け|焦げ|焦が|水ぶくれ|水膨れ|水疱|低温やけど)"),
    ("ja", "melt", r"(?:溶け|溶か|とけて|熔け|過熱|異常発熱|熱すぎ|熱くなりすぎ|高温になり)"),
    ("ja", "shock", r"(?:感電|ビリッ|ビリビリ)"),
    ("ja", "gas", r"(?:ガス漏れ|ガス臭|ガスの臭|ガスのにお|ガスの匂い)"),
    ("ja", "explosion", r"(?:爆発|破裂|ばくはつ)"),
    ("ja", "smell", r"(?:焦げ臭|焦げくさ|異臭|変な臭|変なにお|変な匂い|プラスチックの臭|プラスチック臭|ゴム臭)"),
    ("ja", "injury", r"(?:怪我|ケガ|けが|負傷|出血|血が|血を|流血|病院|救急)"),
    ("ja", "cut", r"(?:切れて|切って(?:しま|怪我)|切り傷|切傷|切ってしま)"),
    ("ja", "allergy", r"(?:アレルギー|かぶれ|発疹|湿疹|腫れ|じんましん|蕁麻疹|かゆみ|痒み)"),
    ("ja", "choking", r"(?:誤飲|誤って飲|窒息|喉に詰|のどに詰|飲み込|小さな部品|小さい部品)"),
    ("ja", "danger", r"(?:危険|危ない|あぶない|有毒|毒性|安全でない|安全性に問題)"),
    # ---- Chinese (Traditional + Simplified)
    ("zh", "fire", r"(?:起火|著火|着火|失火|火災|火灾|起火燒|燒起來|烧起来|火焰|火苗|冒火)"),
    ("zh", "smoke", r"(?:冒煙|冒烟|煙霧|烟雾|有煙|有烟|煙味|烟味)"),
    ("zh", "spark", r"(?:火花|打火|短路)"),
    ("zh", "burn", r"(?:燒傷|烧伤|燙傷|烫伤|灼傷|灼伤|燒到|烧到|燙到|烫到|燙腳|烫脚|燒焦|烧焦|燒壞|烧坏|燒掉|烧掉|燙手|烫手|水泡|起泡|燒毀|烧毁)"),
    ("zh", "melt", r"(?:融化|熔化|熔掉|化掉|溶化|過熱|过热|太燙|太烫|很燙|很烫|發燙|发烫|燙得)"),
    ("zh", "shock", r"(?:觸電|触电|電到|电到|電擊|电击|漏電|漏电)"),
    ("zh", "gas", r"(?:漏氣|漏气|瓦斯味|瓦斯外洩|瓦斯漏|煤氣味|煤气味|煤氣漏|煤气漏|天然氣味)"),
    ("zh", "explosion", r"(?:爆炸|爆裂|炸開|炸开|爆開|爆开)"),
    ("zh", "smell", r"(?:焦味|塑膠味|塑料味|燒焦味|烧焦味|異味|异味|怪味|臭味)"),
    ("zh", "injury", r"(?:受傷|受伤|傷到|伤到|傷口|伤口|流血|出血|送醫|送医|急診|急诊|住院|骨折)"),
    ("zh", "cut", r"(?:割傷|割伤|割到|割破|劃傷|划伤|劃破|划破|刺傷|刺伤)"),
    ("zh", "allergy", r"(?:過敏|过敏|紅疹|红疹|起疹|濕疹|湿疹|紅腫|红肿|腫起|肿起|發炎|发炎|搔癢|瘙痒)"),
    ("zh", "choking", r"(?:窒息|噎到|噎住|誤吞|误吞|吞下|吞進|吞进|小零件|小部件|卡喉)"),
    ("zh", "danger", r"(?:危險|危险|有毒|不安全|安全隱患|安全隐患|安全問題|安全问题)"),
    # ---- chemical / illness / sharp-edge (footwear and clothing: glue, dye, nails, metal parts)
    ("en", "chemical", _B + r"(?:skin reaction|chemical (?:smell|odou?r|burn\w*)|dizz\w*|nause\w*|made me (?:sick|ill)|vomit\w*|sharp (?:metal|edge|nail|piece)|nails? (?:poking|sticking|through)|poked through)" + _E),
    ("es", "chemical", _B + r"(?:olor quimico|mareo\w*|mareada|mareado|nauseas?|vomit\w*|me siento mal|clavo\w* (?:sobresal\w*|salia\w*)|filo cortante)" + _E),
    ("de", "chemical", _B + r"(?:chemisch\w* geruch|schwindel\w*|uebel\w*|ubel\w*|uebelkeit|ubelkeit|erbrech\w*|scharfe? (?:kante|metall\w*)|nagel\w* (?:ragt\w*|stand\w*))" + _E),
    ("fr", "chemical", _B + r"(?:odeur chimique|vertige\w*|nausee\w*|vomi\w*|rends? malade|rendu malade|clou\w* (?:depasse\w*|sortait)|bord tranchant)" + _E),
    ("ja", "chemical", r"(?:めまい|吐き気|気分が悪|化学臭|薬品臭|接着剤の臭|釘が出|尖った|鋭い)"),
    ("zh", "chemical", r"(?:頭暈|头晕|噁心|恶心|想吐|化學味|化学味|刺鼻|釘子露|钉子露|尖銳|尖锐)"),
]
HARM_PATTERNS = [(lang, hazard, re.compile(pat)) for lang, hazard, pat in _HARM]
COVERED_LANGUAGES = ("en", "es", "de", "fr", "ja", "zh")

# --------------------------------------------------------------------------------------------- fault language
# Generic "something is wrong with the product" words. Only meaningful on a GATED product (rule 2).
_FAULT: list[tuple[str, str]] = [
    ("en", _B + r"(?:broken|broke|defective|faulty|malfunction\w*|not working|stopped working|doesn'?t work|does not work|"
           r"won'?t (?:turn on|switch on|heat|light|ignite|start|charge|boil)|(?:isn'?t|not) heating|no longer (?:heats|works|lights)|"
           r"dead|damaged|cracked|leak(?:s|ed|ing)?|flicker\w*|buzz\w*|crackl\w*|tripp?ed|blew|blown|died|fault\w*|failed|failure)" + _E),
    ("es", _B + r"(?:roto|rota|averiad\w*|defectuos\w*|no funciona|dejo de funcionar|no enciende|no calienta|estropead\w*|"
           r"danad\w*|dano\b|falla\w*|fallo\w*|gotea\w*|pierde|fundid\w*|no carga|no prende)" + _E),
    ("de", _B + r"(?:kaputt|defekt\w*|funktioniert nicht|geht nicht|ohne funktion|beschaedigt\w*|beschadigt\w*|undicht|flackert|"
           r"heizt nicht|schaltet nicht|laedt nicht|ladt nicht|ausgefallen|stoerung\w*|storung\w*)" + _E),
    ("fr", _B + r"(?:casse\w*|defectueu\w*|en panne|ne fonctionne (?:pas|plus)|ne marche (?:pas|plus)|abime\w*|endommag\w*|"
           r"fuit\b|fuite\w*|ne chauffe (?:pas|plus)|ne s'allume|ne charge pas|grille\w*|defaut\w*)" + _E),
    ("ja", r"(?:壊れ|故障|動かな|動作しな|つかない|点かない|付かない|不良|破損|漏れ|ちらつ|温まらな|あたたまらな|加熱しな|使えな|不具合|電源が入らな|充電できな|充電されな)"),
    ("zh", r"(?:壞了|壞掉|损坏|損壞|故障|不能用|無法使用|无法使用|無法開|无法开|沒反應|没反应|不亮|不熱|不热|漏水|漏液|瑕疵|異常|异常|"
           r"不通電|不通电|失靈|失灵|有問題|有问题|不能開機|不能开机|不充電|不充电)"),
]
FAULT_PATTERNS = [(lang, re.compile(pat)) for lang, pat in _FAULT]
FAULT_REASONS = frozenset({"DAMAGED"})  # LLM reasons that count as a reported fault (escalate-only)
# The only reasons that let a hazard-class product (GATED_CLASSES) skip the safety review: they say nothing about how
# the product works. Any other reading (DAMAGED, NOT_AS_DESCRIBED, OTHER, UNKNOWN) goes to a person, whatever words
# the customer used. This replaces "block if the customer used a word from our fault list" for these products: a
# fault list can never be complete ("keeps tripping", "hot to touch", "battery bulging" were all missing from it),
# a short list of clearly harmless reasons can. Harm language still flags every product, and the fault words still
# flag even with a clear reason ("wrong size, and it sparked"). Escalate-only: nothing that was flagged before is
# flagged less (tests/test_safety_reasons.py checks that against the previous rule).
CLEAR_REASONS = frozenset({"SIZE_MISMATCH", "CHANGED_MIND", "WRONG_ITEM"})

# --------------------------------------------------------------------------------------------- product class
def _singular(word: str) -> str:
    """Conservative English plural -> singular for MATCHING only (never shown or stored): heaters -> heater,
    stoves -> stove, batteries -> battery, torches -> torch. Short words and -ss / -us / -is words (gas, glass, bus,
    iris) are left alone."""
    if len(word) < 4 or not word.endswith("s") or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    return word[:-1]


def class_text(*parts: object) -> str:
    """Text the product-class rules read: normalised, every non-letter/digit run (hyphen, '>', '&', comma, slash)
    turned into one space, and every word reduced to its singular form. Channel3 sends category PATHS made of plural
    leaves ("Sporting Goods > ... > Camping Stoves", "... > Hair Dryers"); the rules below are written in the
    singular, so both sides must be brought to the same form before they are compared."""
    text = re.sub(r"[\W_]+", " ", normalize(" ".join(str(p or "") for p in parts)))
    return " ".join(_singular(w) for w in text.split())


# Rules are written for class_text(): lowercase singular words, no punctuation (so "e-bike" arrives as "e bike").
_CLASS_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("GAS", re.compile(r"\b(gas|propane|butane|lpg|burner|stove|lighter|regulator|"
                       r"torch|fuel|gasoline|kerosene|oxygen tank|fireplace)\b")),
    ("MAINS_HEATING", re.compile(r"\b(kettle|heater|heating|toaster|iron|hair ?dryer|oven|fryer|air ?fryer|cooker|grill|hob|"
                                 r"electric blanket|heated|hot plate|radiator|boiler|water heater|space heater|"
                                 r"straightener|steamer|hot air|"
                                 r"heat gun|heat tool|glue gun|wood burning|sauna|steam (?:cleaner|inhaler|mop|press|generator)|"
                                 r"(?:bottle|wax|plate|dish|oil|stone|food|beverage|bed|foot) warmer|hot dog roller)\b")),
    ("BATTERY_THERMAL", re.compile(r"\b(battery|power ?bank|e ?bike|e ?scooter|scooter|vape|lithium|li ?ion|rechargeable|"
                                   r"hand warmer|heated (?:jacket|gloves|insoles|vest)|hoverboard|"
                                   r"flashlight|headlamp|jump starter|robotic toy|"
                                   r"remote control (?:toy|car|truck|boat|watercraft|helicopter|plane|robot|tank|airship|blimp|motorcycle))\b")),
    ("MAINS_ELECTRIC", re.compile(r"\b(lamp|light|lighting|charger|adapter|adaptor|extension|power strip|socket|plug|appliance|"
                                  r"blender|vacuum|fan|mixer|electric|electrical|electronic\w*|mains|cable|speaker|monitor|"
                                  r"tv|television|router|dryer|washer|microwave|fridge|freezer|surge|"
                                  r"generator|inverter|power (?:tool|drill)|powered|compressor|welder|plasma cutter|"
                                  r"welding gun)\b")),
]
_CATEGORY_TO_CLASS = {"appliance": "MAINS_ELECTRIC", "appliances": "MAINS_ELECTRIC", "lighting": "MAINS_ELECTRIC",
                      "electronics": "MAINS_ELECTRIC", "electrical": "MAINS_ELECTRIC", "heating": "MAINS_HEATING",
                      "outdoor-gas": "GAS", "gas": "GAS", "batteries": "BATTERY_THERMAL"}

# Documented allowlist of NON-hazard category leaves. A taxonomy leaf can contain a hazard word without being a hazard
# device ("Hair Extensions", "Pipe Caps & Plugs", "Washers" the hardware kind, fireplace grates ...). Each entry is the
# LAST TWO segments of a category path ("parent > leaf"); only an exact two-segment match exempts, so a path cut short by
# the 120-character limit (parent missing) is NOT exempt and stays gated. An exempt category contributes no words, and
# the leaf's own phrase is also removed from the product name; every other word of the name is still read, so a hazard
# title ("Heated Hair Extensions Clip") in an exempt category is still gated. This is the ONLY place a category can lose
# a hazard word; nothing a plain keyword matched on a product NAME alone is affected. Every entry has a test, and the
# sibling leaves that ARE hazards (Firewood & Fuel, Wood Stove Fans & Blowers, Pressure Cookers ...) are tested to stay gated.
NON_HAZARD_LEAVES: tuple[str, ...] = (
    "Pet Supplies > Pet Leash Extensions",
    "Hair Accessories > Hair Extensions",
    "Drill & Screwdriver Accessories > Drill Bit Extensions",
    "Bicycle Parts > Bicycle Handlebar Extensions",
    "Hardware Fasteners > Washers",
    "Plumbing Fittings & Supports > Pipe Adapters & Bushings",
    "Plumbing Fittings & Supports > Pipe Caps & Plugs",
    "Lawn Mower Accessories > Lawn Mower Mulch Plugs & Plates",
    "Tool Accessories > Tool Sockets",
    "Bicycle Parts > Bicycle Tire Valve Adapters",
    "Microscope Accessories > Microscope Eyepieces & Adapters",
    "Towed Water Sports > Water Sport Tow Cables",
    "Bicycle Parts > Bicycle Cables",
    "Watercraft Steering Parts > Watercraft Steering Cables",
    "Kitchen Tools & Utensils > Pastry Blenders",
    "Kitchen Tools & Utensils > Salad Dressing Mixers & Shakers",
    "Gardening Accessories > Gardening Scooters, Seats & Kneelers",
    "Cookware > Dutch Ovens",
    "Cookware > Double Boilers",
    "Cookware Accessories > Steamer Baskets",
    "Clothing Accessories > Decorative Fans",
    "Fertility Monitors and Ovulation Tests > Ovulation Tests",
    "Coffee Makers & Espresso Machines > French Presses",
    "Sauna Accessories > Sauna Buckets & Ladles",
    "Fireplace & Wood Stove Accessories > Bellows",
    "Fireplace & Wood Stove Accessories > Fireplace & Wood Stove Grates",
    "Fireplace & Wood Stove Accessories > Fireplace Andirons",
    "Fireplace & Wood Stove Accessories > Fireplace Reflectors",
    "Fireplace & Wood Stove Accessories > Fireplace Screens",
    "Fireplace & Wood Stove Accessories > Fireplace Tools",
    "Fireplace & Wood Stove Accessories > Hearth Pads",
    "Fireplace & Wood Stove Accessories > Log Rack & Carrier Accessories",
    "Fireplace & Wood Stove Accessories > Log Racks & Carriers",
    "Power & Electrical Supplies > Wire Caps & Nuts",
    "Power & Electrical Supplies > Electrical Mount Boxes & Brackets",
    "Conduit & Housings > Electrical Conduit",
    "Conduit & Housings > Heat-Shrink Tubing",
    "Lighting & Studio > Studio Backgrounds",
    "Lighting & Studio > Studio Stand & Mount Accessories",
    "Lighting & Studio > Studio Stands & Mounts",
    "Studio Lighting Controls > Flash Diffusers",
    "Studio Lighting Controls > Flash Reflectors",
    "Studio Lighting Controls > Lighting Filters & Gobos",
    "Studio Lighting Controls > Softboxes",
)


def _segments(category: str) -> tuple[str, ...]:
    return tuple(class_text(seg) for seg in category.split(">") if seg.strip())


_EXEMPT: dict[tuple[str, ...], str] = {_segments(e): _segments(e)[-1] for e in NON_HAZARD_LEAVES}


def exempt_leaf(category: str | None) -> str | None:
    """The leaf phrase when the category path ends in an allowlisted non-hazard (parent, leaf) pair, else None."""
    seg = _segments(str(category or ""))
    return _EXEMPT.get(seg[-2:]) if len(seg) >= 2 else None


def product_class(product: dict | None) -> str:
    """Safety class from the catalogue category + product name (code, not AI). Unknown product -> NONE; the
    harm-language rule still applies to it."""
    if not product:
        return "NONE"
    cat = normalize(str(product.get("category") or ""))
    explicit = str(product.get("safety_class") or "")
    if explicit in GATED_CLASSES:
        return explicit
    leaf = exempt_leaf(str(product.get("category") or ""))
    if leaf:  # allowlisted non-hazard leaf: the category adds no words, the leaf phrase is dropped from the name too
        text = re.sub(rf"\b{re.escape(leaf)}\b", " ", class_text(product.get("name")))
    else:
        text = class_text(product.get("name"), cat)
    for cls, rx in _CLASS_RULES[:3]:  # the specific hazards first: gas, heating, battery / thermal
        if rx.search(text):
            return cls
    if cat in _CATEGORY_TO_CLASS:
        return _CATEGORY_TO_CLASS[cat]
    return "MAINS_ELECTRIC" if _CLASS_RULES[3][1].search(text) else "NONE"


# --------------------------------------------------------------------------------------------- the gate
@dataclass(frozen=True)
class Signal:
    layer: str      # "pattern" (code), "llm-reason" (the model's own label) or "ai" (opt-in classifier); both escalate-only
    kind: str       # hazard word group (burn / melt / ...) or "fault"
    language: str
    match: str

    def to_dict(self) -> dict:
        return {"layer": self.layer, "kind": self.kind, "language": self.language, "match": self.match}


@dataclass(frozen=True)
class SafetyAssessment:
    flagged: bool
    trigger: str  # "harm_language" | "gated_product_fault" | "gated_product_unclear" | "ai_classifier" | "none"
    product_class: str
    signals: tuple[Signal, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        if not self.flagged:
            return "No safety signal."
        seen = ", ".join(dict.fromkeys(f"{s.kind} ({s.language}: “{s.match}”)" if s.layer == "pattern"
                                       else f"{s.kind} ({s.match})" for s in self.signals))
        if self.trigger == "ai_classifier":
            return f"AI safety screen (second layer) asked for a human to read this message: {seen}."
        if self.trigger == "harm_language":
            return f"Harm / injury / hazard language in the customer's message: {seen}."
        if self.trigger == "gated_product_unclear":
            return (f"A {self.product_class} product returned for a reason that may concern how it works ({seen}): "
                    "a person reads it before any refund. Only a wrong size, a wrong item or a change of mind skips "
                    "this review for this kind of product.")
        return f"Reported fault on a {self.product_class} product: {seen}."

    def to_dict(self) -> dict:
        return {"flagged": self.flagged, "trigger": self.trigger, "product_class": self.product_class,
                "rule_version": SAFETY_RULE_VERSION, "signals": [s.to_dict() for s in self.signals]}


_SPACED = re.compile(r"(?<![a-z0-9])(?:[a-z][ .\-_*]){2,}[a-z](?![a-z0-9])")


def variants(message: str | None) -> list[str]:
    """The normalised text, plus the same text with letter-spaced words rejoined ("s m o k e", "b.u.r.n"). Both are
    scanned; a hit in either counts."""
    n = normalize(message)
    joined = _SPACED.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), n)
    return [n] if joined == n else [n, joined]


def _first(rx: re.Pattern[str], message: str | None) -> str | None:
    for text in variants(message):
        m = rx.search(text)
        if m:
            return m.group(0)[:40]
    return None


def scan_harm(message: str | None) -> list[Signal]:
    out: list[Signal] = []
    for lang, hazard, rx in HARM_PATTERNS:
        hit = _first(rx, message)
        if hit:
            out.append(Signal("pattern", hazard, lang, hit))
    return out


def scan_fault(message: str | None) -> list[Signal]:
    out: list[Signal] = []
    for lang, rx in FAULT_PATTERNS:
        hit = _first(rx, message)
        if hit:
            out.append(Signal("pattern", "fault", lang, hit))
    return out


def assess(message: str | None, product: dict | None = None, llm_reason: str | None = None,
           intent: str | None = None) -> SafetyAssessment:
    """The Safety Gate. `llm_reason` is the extractor's reading of the message. For a hazard-class product it must be
    one of CLEAR_REASONS to skip the review; for every product it can only turn the gate ON, never off. An order-status
    question (intent ORDER_STATUS) is not a return. With no reading at all (llm_reason None) only the word rules run."""
    cls = product_class(product)
    harm = scan_harm(message)
    if harm:
        return SafetyAssessment(True, "harm_language", cls, tuple(harm))
    if cls in GATED_CLASSES:
        fault = scan_fault(message)
        if llm_reason in FAULT_REASONS:
            fault.append(Signal("llm-reason", "fault", "-", f"LLM reason {llm_reason}"))
        if fault:
            return SafetyAssessment(True, "gated_product_fault", cls, tuple(fault))
        if llm_reason is not None and llm_reason not in CLEAR_REASONS and intent != "ORDER_STATUS":
            return SafetyAssessment(True, "gated_product_unclear", cls,
                                    (Signal("llm-reason", "unclear reason", "-", f"reason {llm_reason}"),))
    return SafetyAssessment(False, "none", cls)


def assess_any(message: str | None, products: list[dict | None] | None = None,
               llm_reason: str | None = None, intent: str | None = None) -> SafetyAssessment:
    """Safety Gate over one or more catalogue products (mixed orders). Escalate-only OR:

    * harm language is product-independent (checked once);
    * a gated-product fault on ANY line is enough;
    * ``llm_reason`` can only add a flag, never remove one.

    An empty / missing product list still runs the harm-language rule (same as ``assess(..., None)``).
    """
    harm_first = assess(message, None, None)
    if harm_first.flagged:
        return harm_first
    seen: list[dict | None] = []
    for p in (products or [None]):
        if p in seen:
            continue
        seen.append(p)
        a = assess(message, p, llm_reason, intent)
        if a.flagged:
            return a
    return harm_first if not seen else assess(message, seen[-1], llm_reason, intent)
