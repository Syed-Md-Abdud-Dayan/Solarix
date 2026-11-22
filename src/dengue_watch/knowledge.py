"""Bilingual (English / Bangla) dengue knowledge base for the Dengue Watch chatbot.

Content follows WHO dengue guidance (2009 classification / 2023 fact sheet) and common
Bangladesh public-health messaging. It is general health education, NOT medical advice or a
diagnosis. Each topic has:

    keywords  - words/phrases that trigger the topic (English + Bangla)
    en / bn   - {"title", "body" (list of bullet strings), "follow_ups" (topic ids / intents)}
"""
from __future__ import annotations

HOTLINES = {
    "en": "Bangladesh: DGHS health hotline 16263, IEDCR hotline 10655, national emergency 999. "
          "Please confirm numbers locally - they can change.",
    "bn": "বাংলাদেশ: স্বাস্থ্য অধিদপ্তরের হটলাইন ১৬২৬৩, আইইডিসিআর হটলাইন ১০৬৫৫, জাতীয় জরুরি সেবা ৯৯৯। "
          "নম্বরগুলো পরিবর্তিত হতে পারে, স্থানীয়ভাবে যাচাই করে নিন।",
}

DISCLAIMER = {
    "en": "General health information, not a diagnosis. If you are worried about a patient, see a doctor.",
    "bn": "এটি সাধারণ স্বাস্থ্যতথ্য, রোগ নির্ণয় নয়। কেউ অসুস্থ হলে চিকিৎসকের পরামর্শ নিন।",
}

EMERGENCY = {
    "en": {
        "title": "Possible dengue danger signs - get medical care NOW",
        "body": [
            "These can be warning signs of severe dengue. Go to the nearest hospital or emergency department immediately; do not wait at home.",
            "Do not give aspirin or ibuprofen (NSAIDs); they raise bleeding risk.",
            "While arranging transport: keep the person lying down, give small frequent sips of ORS or clean fluids if they can swallow, and stay with them.",
            "Tell the doctor the day the fever started and any bleeding, vomiting or urine change.",
        ],
    },
    "bn": {
        "title": "ডেঙ্গুর বিপদ-চিহ্ন হতে পারে - এখনই চিকিৎসা নিন",
        "body": [
            "এগুলো মারাত্মক ডেঙ্গুর সতর্কসংকেত হতে পারে। দেরি না করে এখনই নিকটস্থ হাসপাতাল বা জরুরি বিভাগে যান।",
            "অ্যাসপিরিন বা আইবুপ্রোফেন (NSAID) দেবেন না; এতে রক্তক্ষরণের ঝুঁকি বাড়ে।",
            "হাসপাতালে নেওয়ার প্রস্তুতির সময় রোগীকে শুইয়ে রাখুন, গিলতে পারলে অল্প অল্প করে ওআরএস বা পরিষ্কার তরল দিন এবং পাশে থাকুন।",
            "ডাক্তারকে জানান জ্বর কবে শুরু হয়েছে এবং রক্তক্ষরণ, বমি বা প্রস্রাব কমে যাওয়ার কথা।",
        ],
    },
}

# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
TOPICS: dict[str, dict] = {
    "what_is": {
        "keywords": ["what is dengue", "dengue fever", "about dengue", "define dengue", "explain dengue", "dengue meaning",
                     "ডেঙ্গু কী", "ডেঙ্গু কি", "ডেঙ্গু জ্বর কী"],
        "en": {"title": "What is dengue?", "body": [
            "Dengue is a viral infection spread by the bite of infected Aedes mosquitoes (mainly Aedes aegypti, also Aedes albopictus).",
            "There are four dengue virus types (DENV-1 to 4). Infection with one gives lasting protection against that type only; a later infection with a different type raises the chance of severe disease.",
            "Most infections are mild or have no symptoms, but a minority progress to severe dengue, which can be fatal without prompt care.",
            "It is not spread directly from person to person."],
            "follow_ups": ["symptoms", "prevention", "transmission"]},
        "bn": {"title": "ডেঙ্গু কী?", "body": [
            "ডেঙ্গু একটি ভাইরাসজনিত রোগ, যা সংক্রমিত এডিস মশার কামড়ে ছড়ায় (প্রধানত এডিস ইজিপ্টাই, এডিস অ্যালবোপিক্টাসও)।",
            "ডেঙ্গু ভাইরাসের চারটি ধরন আছে (DENV-1 থেকে 4)। একটি ধরনে সংক্রমিত হলে শুধু সেই ধরনের বিরুদ্ধে দীর্ঘস্থায়ী সুরক্ষা মেলে; পরে ভিন্ন ধরনে আক্রান্ত হলে গুরুতর রোগের ঝুঁকি বাড়ে।",
            "বেশিরভাগ ক্ষেত্রে উপসর্গ মৃদু বা অনুপস্থিত থাকে, তবে কিছু রোগী গুরুতর ডেঙ্গুতে আক্রান্ত হন, যা দ্রুত চিকিৎসা না পেলে প্রাণঘাতী হতে পারে।",
            "এটি সরাসরি একজন থেকে আরেকজনে ছড়ায় না।"],
            "follow_ups": ["symptoms", "prevention", "transmission"]},
    },
    "symptoms": {
        "keywords": ["symptom", "sign of dengue", "how do i know", "dengue feel", "fever headache", "rash", "pain behind eyes",
                     "উপসর্গ", "লক্ষণ", "লক্ষন"],
        "en": {"title": "Dengue symptoms", "body": [
            "Symptoms usually start 4-10 days after the bite and last 2-7 days.",
            "Sudden high fever (often 39-40 C) plus at least two of: severe headache, pain behind the eyes, muscle/joint/bone pain, nausea or vomiting, skin rash, swollen glands, mild bleeding (nose/gums, easy bruising).",
            "The most dangerous period is often when the fever FALLS (day 3-7): that is when severe dengue can develop. A patient who feels 'better' still needs close monitoring.",
            "Many cases look like flu, typhoid or chikungunya, so a blood test is needed to confirm."],
            "follow_ups": ["warning_signs", "testing", "home_care"]},
        "bn": {"title": "ডেঙ্গুর লক্ষণ", "body": [
            "মশার কামড়ের ৪-১০ দিন পর উপসর্গ শুরু হয় এবং সাধারণত ২-৭ দিন থাকে।",
            "হঠাৎ তীব্র জ্বর (প্রায়ই ৩৯-৪০ ডিগ্রি সেলসিয়াস) এবং সঙ্গে অন্তত দুটি: তীব্র মাথাব্যথা, চোখের পেছনে ব্যথা, পেশি/হাড়/জোড়ায় ব্যথা, বমি বমি ভাব বা বমি, ত্বকে লালচে দাগ, গ্রন্থি ফোলা, সামান্য রক্তক্ষরণ (নাক/মাড়ি, সহজে কালশিটে)।",
            "সবচেয়ে ঝুঁকিপূর্ণ সময় প্রায়ই জ্বর কমে যাওয়ার সময় (৩-৭ দিন): তখন গুরুতর ডেঙ্গু দেখা দিতে পারে। 'ভালো লাগছে' মনে হলেও রোগীকে সতর্কভাবে পর্যবেক্ষণে রাখতে হবে।",
            "ফ্লু, টাইফয়েড বা চিকুনগুনিয়ার সঙ্গে লক্ষণ মিলে যায়, তাই নিশ্চিত হতে রক্ত পরীক্ষা দরকার।"],
            "follow_ups": ["warning_signs", "testing", "home_care"]},
    },
    "warning_signs": {
        "keywords": ["warning sign", "danger sign", "severe dengue", "when to go to hospital", "when to see doctor", "when hospital",
                     "emergency", "serious", "critical phase", "dengue shock", "bleeding", "bleed", "vomiting", "abdominal pain", "stomach pain", "রক্তক্ষরণ", "হাসপাতালে", "বিপদ", "বিপদ চিহ্ন", "গুরুতর ডেঙ্গু", "সতর্কতা চিহ্ন"],
        "en": {"title": "Warning signs of severe dengue (go to hospital immediately)", "body": [
            "Severe or continuous abdominal pain / tenderness",
            "Persistent vomiting (about 3+ times in 24 h) or cannot keep fluids down",
            "Bleeding: gums, nose, blood in vomit, black or bloody stool, heavy periods",
            "Extreme tiredness, restlessness, drowsiness, irritability or confusion",
            "Fast breathing or difficulty breathing",
            "Cold, clammy, pale skin; very weak pulse; cold hands and feet",
            "Passing very little urine; intense thirst",
            "Sudden drop in fever with the patient getting worse, not better",
            "Children, pregnant women, older adults and people with diabetes, heart/kidney disease or obesity should be seen early, even without these signs."],
            "follow_ups": ["home_care", "hotline"]},
        "bn": {"title": "গুরুতর ডেঙ্গুর সতর্কসংকেত (সঙ্গে সঙ্গে হাসপাতালে যান)", "body": [
            "পেটে তীব্র বা একটানা ব্যথা",
            "ক্রমাগত বমি (২৪ ঘণ্টায় প্রায় ৩ বার বা বেশি) অথবা তরল পেটে না থাকা",
            "রক্তক্ষরণ: মাড়ি বা নাক দিয়ে, বমিতে রক্ত, কালো বা রক্তমাখা পায়খানা, অতিরিক্ত মাসিক রক্তস্রাব",
            "অতিরিক্ত দুর্বলতা, অস্থিরতা, ঝিমানো, খিটখিটে ভাব বা বিভ্রান্তি",
            "দ্রুত শ্বাস বা শ্বাসকষ্ট",
            "ঠান্ডা, ঘামে ভেজা, ফ্যাকাসে ত্বক; দুর্বল নাড়ি; হাত-পা ঠান্ডা",
            "প্রস্রাব খুব কমে যাওয়া; অতিরিক্ত তৃষ্ণা",
            "জ্বর হঠাৎ কমে গিয়ে রোগীর অবস্থা আরও খারাপ হওয়া",
            "শিশু, গর্ভবতী নারী, বয়স্ক এবং ডায়াবেটিস, হৃদরোগ, কিডনি রোগ বা স্থূলতায় আক্রান্তদের এই লক্ষণ ছাড়াও আগেভাগে চিকিৎসকের কাছে নেওয়া উচিত।"],
            "follow_ups": ["home_care", "hotline"]},
    },
    "prevention": {
        "keywords": ["prevent", "protect", "avoid dengue", "stop dengue", "control mosquito", "mosquito control", "repellent", "mosquito net",
                     "প্রতিরোধ", "প্রতিকার", "রক্ষা", "মশা নিয়ন্ত্রণ", "মশারি"],
        "en": {"title": "How to prevent dengue", "body": [
            "Empty, scrub or cover anything that holds stagnant water at least once a week: flower pots and trays, coolers/AC trays, buckets, tyres, drums, coconut shells, roof gutters, discarded containers.",
            "Aedes bites mainly in the DAYTIME (early morning and late afternoon): use repellent (DEET/picaridin/IR3535), wear long sleeves, and sleep under a net during daytime naps.",
            "Fit window and door screens; keep rooms free of dark hiding places (hanging clothes, clutter).",
            "Cover water storage tightly; add larvae-eating fish where appropriate; ask your city corporation about larviciding.",
            "If someone in the household has dengue, protect them from mosquito bites (net/screens) so the virus is not passed on to others.",
            "Join community clean-up drives; mosquitoes breed within about 100-200 m of home."],
            "follow_ups": ["breeding", "vaccine", "season"]},
        "bn": {"title": "ডেঙ্গু প্রতিরোধের উপায়", "body": [
            "সপ্তাহে অন্তত একবার জমে থাকা পানি খালি করুন, ঘষে পরিষ্কার করুন বা ঢেকে রাখুন: ফুলের টব ও ট্রে, এসি/কুলারের ট্রে, বালতি, টায়ার, ড্রাম, নারিকেলের খোসা, ছাদের নালা, ফেলে দেওয়া পাত্র।",
            "এডিস মশা প্রধানত দিনের বেলায় (সকাল ও বিকেল) কামড়ায়: মশা-নিরোধক ক্রিম/স্প্রে ব্যবহার করুন, লম্বা হাতা কাপড় পরুন এবং দিনের ঘুমেও মশারি ব্যবহার করুন।",
            "জানালা-দরজায় নেট লাগান; ঘরে অন্ধকার কোণ, ঝুলন্ত কাপড় ও অপ্রয়োজনীয় জিনিস জমতে দেবেন না।",
            "পানির পাত্র ভালোভাবে ঢেকে রাখুন; সিটি কর্পোরেশনের লার্ভিসাইডিং কার্যক্রমের খোঁজ নিন।",
            "পরিবারে কেউ আক্রান্ত হলে তাকে মশারি/নেটের ভেতরে রাখুন, যাতে অন্যদের মধ্যে ছড়াতে না পারে।",
            "এলাকাভিত্তিক পরিচ্ছন্নতা কর্মসূচিতে অংশ নিন; এডিস মশা সাধারণত বাড়ির ১০০-২০০ মিটারের মধ্যেই বংশবিস্তার করে।"],
            "follow_ups": ["breeding", "vaccine", "season"]},
    },
    "breeding": {
        "keywords": ["breeding", "breed", "larva", "larvae", "stagnant water", "aedes", "where do mosquito", "eggs", "fogging", "spray", "larvicide",
                     "বংশবিস্তার", "লার্ভা", "জমে থাকা পানি", "এডিস", "ফগিং"],
        "en": {"title": "Aedes mosquito and breeding sites", "body": [
            "Aedes lays eggs just above the waterline of small, clean, still water. Eggs can survive dry for months and hatch when rain refills the container.",
            "Egg to adult takes about 7-10 days in warm weather - so a weekly container check breaks the cycle.",
            "Typical sites in Dhaka-type cities: construction-site water, rooftop tanks and gutters, AC/fridge trays, flower vases, tyres, plastic waste.",
            "Fogging/adult-mosquito spraying only kills flying adults for a short time; removing breeding sites and larviciding are what actually reduce numbers."],
            "follow_ups": ["prevention", "rain_link"]},
        "bn": {"title": "এডিস মশা ও বংশবিস্তারের স্থান", "body": [
            "এডিস মশা ছোট, পরিষ্কার ও স্থির পানির পাত্রের পানির ঠিক ওপরে ডিম পাড়ে। ডিম শুকনো অবস্থায় কয়েক মাস বেঁচে থাকতে পারে এবং বৃষ্টিতে পানি জমলে ফুটে যায়।",
            "উষ্ণ আবহাওয়ায় ডিম থেকে পূর্ণাঙ্গ মশা হতে প্রায় ৭-১০ দিন লাগে - তাই সাপ্তাহিক পাত্র পরীক্ষা চক্র ভেঙে দেয়।",
            "ঢাকার মতো শহরে সাধারণ স্থান: নির্মাণস্থলের পানি, ছাদের ট্যাংক ও নালা, এসি/ফ্রিজের ট্রে, ফুলদানি, টায়ার, প্লাস্টিক বর্জ্য।",
            "ফগিং শুধু উড়ন্ত প্রাপ্তবয়স্ক মশা অল্প সময়ের জন্য মারে; প্রজননস্থল নষ্ট করা ও লার্ভিসাইডিংই মশার সংখ্যা আসলে কমায়।"],
            "follow_ups": ["prevention", "rain_link"]},
    },
    "treatment": {
        "keywords": ["treatment", "treat", "cure", "medicine", "medication", "paracetamol", "napa", "ibuprofen", "aspirin", "antibiotic", "drug",
                     "চিকিৎসা", "ওষুধ", "প্যারাসিটামল", "নাপা", "এন্টিবায়োটিক", "অ্যান্টিবায়োটিক"],
        "en": {"title": "Dengue treatment", "body": [
            "There is no specific antiviral drug. Care is supportive: rest, plenty of fluids and monitoring.",
            "For fever/pain, paracetamol (acetaminophen) is generally used - follow the label or your doctor for the dose, especially for children. I do not give dosing.",
            "AVOID aspirin, ibuprofen, diclofenac and other NSAIDs, and avoid steroids or antibiotics unless a doctor prescribes them: NSAIDs raise bleeding risk and antibiotics do not treat a virus.",
            "Severe dengue needs hospital care: IV fluids, close monitoring of blood pressure, haematocrit and platelets, and sometimes blood products."],
            "follow_ups": ["home_care", "warning_signs", "diet"]},
        "bn": {"title": "ডেঙ্গুর চিকিৎসা", "body": [
            "ডেঙ্গুর নির্দিষ্ট কোনো অ্যান্টিভাইরাল ওষুধ নেই। চিকিৎসা সহায়ক: বিশ্রাম, প্রচুর তরল ও নিয়মিত পর্যবেক্ষণ।",
            "জ্বর/ব্যথায় সাধারণত প্যারাসিটামল ব্যবহার করা হয় - মাত্রা ওষুধের গায়ের নির্দেশনা বা চিকিৎসকের কাছ থেকে জেনে নিন, বিশেষ করে শিশুদের ক্ষেত্রে। আমি ডোজ বলি না।",
            "অ্যাসপিরিন, আইবুপ্রোফেন, ডাইক্লোফেনাক ও অন্যান্য NSAID এড়িয়ে চলুন; চিকিৎসক না দিলে স্টেরয়েড বা অ্যান্টিবায়োটিক নেবেন না: NSAID রক্তক্ষরণের ঝুঁকি বাড়ায় আর অ্যান্টিবায়োটিক ভাইরাসে কাজ করে না।",
            "গুরুতর ডেঙ্গুতে হাসপাতালে ভর্তি লাগে: শিরায় স্যালাইন, রক্তচাপ, হেমাটোক্রিট ও প্লাটিলেট পর্যবেক্ষণ এবং প্রয়োজনে রক্ত/রক্তের উপাদান।"],
            "follow_ups": ["home_care", "warning_signs", "diet"]},
    },
    "home_care": {
        "keywords": ["home care", "at home", "take care", "look after", "recover", "recovery", "rest", "monitor", "fluids", "ors", "hydration",
                     "বাসায়", "বাড়িতে", "যত্ন", "সেরে", "পুনরুদ্ধার", "ওআরএস", "খাবার স্যালাইন"],
        "en": {"title": "Caring for a dengue patient at home (mild cases)", "body": [
            "Get a doctor's assessment and a blood test first; follow the doctor's monitoring plan (often daily blood counts during days 3-7).",
            "Fluids: ORS, oral saline, rice water, coconut water, soup, fruit juice; aim for regular sips all day. Pale-yellow urine every 4-6 hours is a good sign.",
            "Rest. Use a bed net so mosquitoes cannot bite the patient and infect others.",
            "Paracetamol for fever as directed by the doctor; no aspirin/ibuprofen. Tepid sponging helps comfort.",
            "Check for warning signs several times a day (see 'warning signs'). If any appear, go to hospital immediately.",
            "Recovery can take 1-2 weeks, with tiredness afterwards. Avoid heavy exertion until the doctor says it is safe."],
            "follow_ups": ["warning_signs", "diet", "platelets"]},
        "bn": {"title": "বাসায় ডেঙ্গু রোগীর যত্ন (মৃদু ক্ষেত্রে)", "body": [
            "আগে চিকিৎসকের মূল্যায়ন ও রক্ত পরীক্ষা করান; চিকিৎসকের পর্যবেক্ষণ-পরিকল্পনা মানুন (প্রায়ই ৩-৭ দিনে প্রতিদিন রক্তের কাউন্ট দেখা হয়)।",
            "তরল: ওআরএস, খাবার স্যালাইন, ভাতের মাড়, ডাবের পানি, স্যুপ, ফলের রস; সারাদিন নিয়মিত অল্প অল্প করে পান করুন। ৪-৬ ঘণ্টায় একবার হালকা হলুদ প্রস্রাব ভালো লক্ষণ।",
            "বিশ্রাম নিন। মশারির ভেতরে রাখুন, যাতে মশা কামড়ে অন্যদের সংক্রমিত না করে।",
            "চিকিৎসকের নির্দেশমতো প্যারাসিটামল; অ্যাসপিরিন/আইবুপ্রোফেন নয়। কুসুম গরম পানিতে গা মুছলে আরাম হয়।",
            "দিনে কয়েকবার সতর্কসংকেত পরীক্ষা করুন ('সতর্ক চিহ্ন' দেখুন)। কোনোটি দেখা দিলে সঙ্গে সঙ্গে হাসপাতালে যান।",
            "সুস্থ হতে ১-২ সপ্তাহ লাগতে পারে, পরে ক্লান্তি থাকে। চিকিৎসক নিরাপদ বললে তবেই ভারী পরিশ্রম করুন।"],
            "follow_ups": ["warning_signs", "diet", "platelets"]},
    },
    "diet": {
        "keywords": ["diet", "food", "eat", "drink", "papaya", "papaya leaf", "juice", "coconut", "kiwi", "pomegranate", "খাবার", "খাদ্য", "পেঁপে", "পেপে", "পেঁপে পাতা", "ডাব"],
        "en": {"title": "Food and drink during dengue", "body": [
            "Eat light, easy-to-digest food as tolerated (rice, soup, porridge, fruit). Small frequent meals are easier when nauseous.",
            "Drink plenty: ORS, clean water, coconut water, juices. Avoid very dark red/brown drinks and foods that could be mistaken for blood in vomit or stool.",
            "Papaya leaf extract: small studies suggest it may raise platelet numbers, but evidence is limited and it does not shorten illness or prevent severe dengue. It is not a replacement for medical monitoring; check with your doctor.",
            "Avoid alcohol, and avoid spicy or oily food if it worsens nausea."],
            "follow_ups": ["platelets", "home_care"]},
        "bn": {"title": "ডেঙ্গুতে খাবার ও পানীয়", "body": [
            "সহনীয় মাত্রায় হালকা, সহজপাচ্য খাবার খান (ভাত, স্যুপ, খিচুড়ি/জাউ, ফল)। বমি বমি ভাব থাকলে অল্প অল্প করে ঘন ঘন খান।",
            "প্রচুর তরল পান করুন: ওআরএস, পরিষ্কার পানি, ডাবের পানি, ফলের রস। বমি বা পায়খানায় রক্তের সঙ্গে গুলিয়ে যেতে পারে এমন গাঢ় লাল/বাদামি পানীয় ও খাবার এড়িয়ে চলুন।",
            "পেঁপে পাতার রস: ছোট গবেষণায় প্লাটিলেট বাড়ার ইঙ্গিত থাকলেও প্রমাণ সীমিত; এটি অসুস্থতার সময় কমায় না, গুরুতর ডেঙ্গুও ঠেকায় না। চিকিৎসকের পর্যবেক্ষণের বিকল্প নয়; খাওয়ার আগে চিকিৎসকের সঙ্গে কথা বলুন।",
            "অ্যালকোহল এড়ান এবং বমি বাড়লে ঝাল বা তেলযুক্ত খাবার বাদ দিন।"],
            "follow_ups": ["platelets", "home_care"]},
    },
    "platelets": {
        "keywords": ["platelet", "platelets", "plt", "blood count", "cbc", "haematocrit", "hematocrit", "hct", "transfusion", "প্লাটিলেট", "প্লেটলেট", "রক্তের কণিকা", "কাউন্ট"],
        "en": {"title": "Platelet count in dengue", "body": [
            "Platelets commonly fall during days 3-7, then recover on their own as the fever settles.",
            "The count by itself does not decide severity. Doctors look at the whole picture: symptoms, warning signs, blood pressure, and rising haematocrit (a sign of plasma leakage).",
            "Platelet transfusion is NOT routinely needed for a low count alone; it is reserved for significant bleeding or very low counts as judged by the treating doctor.",
            "A normal count never cancels the need to watch for warning signs, and a low count does not by itself mean you must be admitted - ask your doctor."],
            "follow_ups": ["warning_signs", "home_care"]},
        "bn": {"title": "ডেঙ্গুতে প্লাটিলেট কাউন্ট", "body": [
            "সাধারণত ৩-৭ দিনে প্লাটিলেট কমে যায়, জ্বর সেরে গেলে আপনা-আপনি আবার বাড়ে।",
            "শুধু কাউন্ট দিয়ে রোগের তীব্রতা বোঝা যায় না। চিকিৎসক পুরো চিত্র দেখেন: উপসর্গ, সতর্কসংকেত, রক্তচাপ ও হেমাটোক্রিট বেড়ে যাওয়া (প্লাজমা চুঁইয়ে যাওয়ার ইঙ্গিত)।",
            "শুধু কাউন্ট কম হলে নিয়মিতভাবে প্লাটিলেট ট্রান্সফিউশন লাগে না; তা গুরুতর রক্তক্ষরণ বা খুব কম কাউন্টে চিকিৎসকের সিদ্ধান্তে দেওয়া হয়।",
            "কাউন্ট স্বাভাবিক হলেও সতর্কসংকেত খেয়াল রাখতে হবে, আবার কাউন্ট কম মানেই ভর্তি নয় - চিকিৎসকের কাছে জেনে নিন।"],
            "follow_ups": ["warning_signs", "home_care"]},
    },
    "testing": {
        "keywords": ["test", "diagnos", "ns1", "igm", "igg", "pcr", "confirm", "blood test", "rapid test", "পরীক্ষা", "এনএস১", "এনএস ১", "নির্ণয়", "টেস্ট"],
        "en": {"title": "Testing for dengue", "body": [
            "NS1 antigen (or PCR): best in the first ~5 days of fever.",
            "IgM / IgG antibodies: become positive from about day 5 onward; a repeat test after a few days may be needed.",
            "A complete blood count (CBC) with platelets and haematocrit helps monitor the illness; it does not confirm dengue by itself.",
            "A negative early test does not fully rule out dengue - if symptoms continue, repeat the test and see a doctor. Government hospitals and many private labs offer these tests."],
            "follow_ups": ["symptoms", "warning_signs"]},
        "bn": {"title": "ডেঙ্গুর পরীক্ষা", "body": [
            "এনএস১ অ্যান্টিজেন (বা পিসিআর): জ্বরের প্রথম ~৫ দিনে সবচেয়ে কার্যকর।",
            "আইজিএম/আইজিজি অ্যান্টিবডি: ৫ম দিনের পর থেকে পজিটিভ হয়; কয়েক দিন পর আবার পরীক্ষা লাগতে পারে।",
            "সিবিসি (প্লাটিলেট ও হেমাটোক্রিটসহ) রোগের অবস্থা পর্যবেক্ষণে সাহায্য করে; এটি একা ডেঙ্গু নিশ্চিত করে না।",
            "শুরুর দিকে নেগেটিভ মানেই ডেঙ্গু নয় তা নিশ্চিত নয় - উপসর্গ থাকলে আবার পরীক্ষা করান ও ডাক্তার দেখান। সরকারি হাসপাতাল ও অনেক বেসরকারি ল্যাবে এই পরীক্ষা হয়।"],
            "follow_ups": ["symptoms", "warning_signs"]},
    },
    "transmission": {
        "keywords": ["spread", "transmit", "transmission", "contagious", "catch", "infect", "bite", "incubation", "human to human", "ছড়ায়", "ছড়ানো", "সংক্রমণ", "ছোঁয়াচে", "কামড়"],
        "en": {"title": "How dengue spreads", "body": [
            "A mosquito bites an infected person, the virus multiplies in the mosquito for about 8-12 days, and then it can infect every person it bites.",
            "Dengue is NOT contagious through touch, coughing or sharing food. Rare routes: mother to baby, blood/organ donation.",
            "A patient is infectious to mosquitoes mainly while febrile (first ~5-7 days) - so keep them under a net.",
            "Incubation: 4-10 days from bite to symptoms."],
            "follow_ups": ["prevention", "breeding"]},
        "bn": {"title": "ডেঙ্গু কীভাবে ছড়ায়", "body": [
            "মশা আক্রান্ত ব্যক্তিকে কামড়ালে ভাইরাস মশার শরীরে প্রায় ৮-১২ দিনে বাড়ে, তারপর সে যাকে কামড়ায় তাকেই সংক্রমিত করতে পারে।",
            "স্পর্শ, কাশি বা একসঙ্গে খাবার খাওয়ার মাধ্যমে ডেঙ্গু ছড়ায় না। বিরল পথ: মা থেকে শিশু, রক্ত/অঙ্গ দান।",
            "রোগী মূলত জ্বর থাকাকালীন (প্রথম ~৫-৭ দিন) মশার জন্য সংক্রামক - তাই তাকে মশারির ভেতরে রাখুন।",
            "ইনকিউবেশন: কামড়ের ৪-১০ দিন পর উপসর্গ।"],
            "follow_ups": ["prevention", "breeding"]},
    },
    "vaccine": {
        "keywords": ["vaccine", "vaccin", "immuniz", "dengvaxia", "qdenga", "tak-003", "টিকা", "ভ্যাকসিন"],
        "en": {"title": "Dengue vaccines", "body": [
            "A dengue vaccine (TAK-003 / Qdenga) is WHO-prequalified (2024) and recommended for children about 6-16 years old in settings with high transmission; Dengvaxia is only for people with a previous confirmed infection.",
            "Vaccines are not yet part of Bangladesh's routine immunisation schedule as far as I know - check with DGHS or your doctor for current availability.",
            "Vaccination, if available, complements - never replaces - mosquito control, because protection is partial."],
            "follow_ups": ["prevention"]},
        "bn": {"title": "ডেঙ্গুর টিকা", "body": [
            "ডেঙ্গুর টিকা (TAK-003 / Qdenga) ২০২৪ সালে ডব্লিউএইচও প্রিকোয়ালিফাইড; উচ্চ সংক্রমণ এলাকায় আনুমানিক ৬-১৬ বছর বয়সী শিশুদের জন্য সুপারিশ করা হয়। ডেঙ্গভ্যাক্সিয়া শুধু আগে নিশ্চিতভাবে আক্রান্ত হওয়া ব্যক্তিদের জন্য।",
            "আমার জানামতে এটি এখনো বাংলাদেশের নিয়মিত টিকাদান সূচির অংশ নয় - বর্তমান প্রাপ্যতা স্বাস্থ্য অধিদপ্তর বা চিকিৎসকের কাছ থেকে জেনে নিন।",
            "টিকা (পাওয়া গেলে) মশা নিয়ন্ত্রণের পরিপূরক, বিকল্প নয়, কারণ সুরক্ষা আংশিক।"],
            "follow_ups": ["prevention"]},
    },
    "children_pregnancy": {
        "keywords": ["child", "children", "kid", "baby", "infant", "toddler", "pregnan", "elderly", "old age", "diabetes", "শিশু", "বাচ্চা", "গর্ভবতী", "বয়স্ক", "ডায়াবেটিস"],
        "en": {"title": "Children, pregnancy and higher-risk groups", "body": [
            "Infants, young children, pregnant women, older adults and people with diabetes, heart, kidney or liver disease, or obesity are at higher risk of severe dengue.",
            "Children can deteriorate quickly: watch for persistent vomiting, belly pain, lethargy, refusal to drink, few wet nappies/urine, bleeding. See a doctor early and do not give any medicine dose without the doctor's advice.",
            "In pregnancy, fever with possible dengue needs prompt medical assessment; dengue near delivery can raise bleeding risks for mother and baby."],
            "follow_ups": ["warning_signs", "hotline"]},
        "bn": {"title": "শিশু, গর্ভাবস্থা ও উচ্চ ঝুঁকির গোষ্ঠী", "body": [
            "ছোট শিশু, গর্ভবতী নারী, বয়স্ক এবং ডায়াবেটিস, হৃদরোগ, কিডনি/লিভার রোগ বা স্থূলতায় আক্রান্তদের গুরুতর ডেঙ্গুর ঝুঁকি বেশি।",
            "শিশুর অবস্থা দ্রুত খারাপ হতে পারে: ক্রমাগত বমি, পেটব্যথা, নিস্তেজ ভাব, পানি পান করতে না চাওয়া, প্রস্রাব কম হওয়া, রক্তক্ষরণ খেয়াল রাখুন। আগেভাগে ডাক্তার দেখান এবং চিকিৎসকের পরামর্শ ছাড়া কোনো ওষুধের ডোজ দেবেন না।",
            "গর্ভাবস্থায় ডেঙ্গুর সম্ভাবনাসহ জ্বর হলে দ্রুত চিকিৎসকের মূল্যায়ন দরকার; প্রসবের কাছাকাছি সময়ে ডেঙ্গু মা ও শিশুর রক্তক্ষরণের ঝুঁকি বাড়াতে পারে।"],
            "follow_ups": ["warning_signs", "hotline"]},
    },
    "vs_other": {
        "keywords": ["chikungunya", "malaria", "typhoid", "covid", "flu", "viral fever", "difference", "same as", "চিকুনগুনিয়া", "ম্যালেরিয়া", "টাইফয়েড", "পার্থক্য"],
        "en": {"title": "Dengue vs other fevers", "body": [
            "Dengue, chikungunya, flu, typhoid, malaria and COVID-19 can all start with fever and body aches, so symptoms alone cannot tell them apart.",
            "Clues: dengue often has severe retro-orbital headache, a falling platelet count and a risky 'critical phase' after the fever; chikungunya typically causes severe joint pain/swelling; typhoid fever builds up over days with abdominal symptoms.",
            "Only tests can separate them (NS1/antibody for dengue). Avoid aspirin/NSAIDs until dengue is excluded."],
            "follow_ups": ["testing", "symptoms"]},
        "bn": {"title": "ডেঙ্গু ও অন্যান্য জ্বরের পার্থক্য", "body": [
            "ডেঙ্গু, চিকুনগুনিয়া, ফ্লু, টাইফয়েড, ম্যালেরিয়া ও কোভিড-১৯ সবই জ্বর ও গা ব্যথা দিয়ে শুরু হতে পারে, তাই শুধু উপসর্গ দেখে আলাদা করা যায় না।",
            "ইঙ্গিত: ডেঙ্গুতে প্রায়ই চোখের পেছনে তীব্র ব্যথা, প্লাটিলেট কমা এবং জ্বর কমার পর ঝুঁকিপূর্ণ 'ক্রিটিক্যাল ফেজ' থাকে; চিকুনগুনিয়ায় সাধারণত জোড়ায় তীব্র ব্যথা/ফোলা; টাইফয়েডে কয়েক দিন ধরে জ্বর বাড়ে ও পেটের সমস্যা থাকে।",
            "শুধু পরীক্ষাই আলাদা করতে পারে (ডেঙ্গুর জন্য এনএস১/অ্যান্টিবডি)। ডেঙ্গু বাদ না যাওয়া পর্যন্ত অ্যাসপিরিন/NSAID এড়িয়ে চলুন।"],
            "follow_ups": ["testing", "symptoms"]},
    },
    "reinfection": {
        "keywords": ["again", "twice", "second time", "reinfect", "immunity", "immune", "serotype", "denv", "দ্বিতীয়বার", "আবার ডেঙ্গু", "সেরোটাইপ"],
        "en": {"title": "Getting dengue again", "body": [
            "Yes, you can get dengue more than once - up to four times, once per virus type.",
            "A second infection with a different type has a higher chance of severe dengue, so people who had dengue before must take warning signs seriously and avoid bites.",
            "Bangladesh has seen shifts in the dominant serotype in some years, which can drive larger outbreaks."],
            "follow_ups": ["warning_signs", "prevention"]},
        "bn": {"title": "আবার ডেঙ্গু হওয়া", "body": [
            "হ্যাঁ, একাধিকবার ডেঙ্গু হতে পারে - চারটি ভাইরাস ধরনের জন্য সর্বোচ্চ চারবার।",
            "ভিন্ন ধরনে দ্বিতীয়বার সংক্রমণে গুরুতর ডেঙ্গুর ঝুঁকি বেশি, তাই আগে ডেঙ্গু হয়ে থাকলে সতর্কসংকেত গুরুত্ব দিন এবং মশার কামড় এড়ান।",
            "কিছু বছরে বাংলাদেশে প্রধান সেরোটাইপ বদলেছে, যা বড় প্রাদুর্ভাব ঘটাতে পারে।"],
            "follow_ups": ["warning_signs", "prevention"]},
    },
    "season": {
        "keywords": ["season", "peak month", "peak season", "monsoon", "when is dengue", "which month", "time of year", "মৌসুম", "বর্ষা", "কোন মাসে", "কোন মাস"],
        "en": {"title": "Dengue season in Bangladesh", "body": [
            "Transmission in Bangladesh follows the monsoon: cases start rising after the rains begin (May-June), peak around August-September and fall by November. This matches the dataset in this project."]},
        "bn": {"title": "বাংলাদেশে ডেঙ্গুর মৌসুম", "body": [
            "বাংলাদেশে সংক্রমণ বর্ষার সঙ্গে সম্পর্কিত: বৃষ্টি শুরুর পর (মে-জুন) রোগী বাড়তে থাকে, আগস্ট-সেপ্টেম্বরে সর্বোচ্চ হয় এবং নভেম্বর নাগাদ কমে আসে। এই প্রকল্পের ডেটার সঙ্গেও এটি মেলে।"]},
    },
    "rain_link": {
        "keywords": ["rain", "rainfall", "weather", "temperature", "humidity", "climate", "why rain", "বৃষ্টি", "আবহাওয়া", "তাপমাত্রা", "আর্দ্রতা"],
        "en": {"title": "Why weather matters", "body": [
            "Rain refills containers and puddles (more breeding sites); warm temperatures (about 26-32 C) speed up mosquito development and shorten the virus's incubation in the mosquito.",
            "The effect is delayed: roughly 1-2 weeks for larvae to become adult mosquitoes, then 1-2 more weeks for infections to turn into reported cases. That is why the model reads rainfall and temperature from past weeks.",
            "Very heavy flooding can also flush larvae out, so the relationship is strongest for moderate, repeated rain."],
            "follow_ups": ["breeding", "season"]},
        "bn": {"title": "আবহাওয়া কেন গুরুত্বপূর্ণ", "body": [
            "বৃষ্টিতে পাত্র ও গর্তে পানি জমে (প্রজননস্থল বাড়ে); উষ্ণ তাপমাত্রা (প্রায় ২৬-৩২ ডিগ্রি) মশার বৃদ্ধি দ্রুত করে এবং মশার শরীরে ভাইরাসের ইনকিউবেশন সময় কমায়।",
            "প্রভাব দেরিতে আসে: লার্ভা থেকে প্রাপ্তবয়স্ক মশা হতে প্রায় ১-২ সপ্তাহ, তারপর সংক্রমণ রিপোর্টেড রোগী হতে আরও ১-২ সপ্তাহ। তাই মডেল আগের সপ্তাহের বৃষ্টি ও তাপমাত্রা দেখে।",
            "অতি ভারী বন্যায় লার্ভা ভেসেও যেতে পারে, তাই মাঝারি ও বারবার বৃষ্টিতে সম্পর্ক সবচেয়ে জোরালো।"],
            "follow_ups": ["breeding", "season"]},
    },
    "hotline": {
        "keywords": ["hotline", "helpline", "phone number", "call", "contact", "dghs", "iedcr", "ambulance", "hospital number", "হটলাইন", "হেল্পলাইন", "ফোন", "যোগাযোগ", "নম্বর"],
        "en": {"title": "Where to get help in Bangladesh", "body": [HOTLINES["en"],
                                                              "For an emergency, go to the nearest hospital. Government medical colleges and district hospitals in Dhaka and other cities run dengue wards during the season."]},
        "bn": {"title": "বাংলাদেশে সাহায্যের জন্য", "body": [HOTLINES["bn"],
                                                  "জরুরি অবস্থায় নিকটস্থ হাসপাতালে যান। মৌসুমে ঢাকা ও অন্যান্য শহরের সরকারি মেডিকেল কলেজ ও জেলা হাসপাতালে ডেঙ্গু ওয়ার্ড চালু থাকে।"]},
    },
    "myths": {
        "keywords": ["myth", "true that", "is it true", "fact", "rumor", "rumour", "fogging kills", "গুজব", "সত্যি কি", "ভুল ধারণা"],
        "en": {"title": "Common dengue myths", "body": [
            "'Dengue spreads from person to person' - No, only via mosquito bites.",
            "'Aedes breeds in dirty drains' - No, it prefers small pools of clean, still water.",
            "'Low platelets always need a transfusion' - No, it is decided by symptoms and bleeding, not the number alone.",
            "'Antibiotics or steroids help' - No, dengue is viral; use them only if a doctor prescribes for another reason.",
            "'Fogging solves the problem' - Only briefly; remove breeding sites to really cut mosquitoes.",
            "'Once I recover I am immune' - Only to that virus type; a second infection can be worse."],
            "follow_ups": ["prevention", "platelets"]},
        "bn": {"title": "ডেঙ্গু নিয়ে প্রচলিত ভুল ধারণা", "body": [
            "'ডেঙ্গু একজন থেকে আরেকজনে ছড়ায়' - না, শুধু মশার কামড়ে।",
            "'এডিস নোংরা নর্দমায় জন্মায়' - না, এরা ছোট, পরিষ্কার, স্থির পানি পছন্দ করে।",
            "'প্লাটিলেট কম হলেই ট্রান্সফিউশন লাগে' - না, এটি উপসর্গ ও রক্তক্ষরণ দেখে ঠিক হয়, শুধু সংখ্যা দেখে নয়।",
            "'অ্যান্টিবায়োটিক বা স্টেরয়েড কাজ করে' - না, ডেঙ্গু ভাইরাসজনিত; অন্য কারণে চিকিৎসক দিলে তবেই।",
            "'ফগিং করলেই সমস্যা শেষ' - শুধু অল্প সময়ের জন্য; আসলে প্রজননস্থল নষ্ট করতে হবে।",
            "'একবার ভালো হলে আর হবে না' - শুধু ওই ধরনের বিরুদ্ধে; দ্বিতীয়বার আরও গুরুতর হতে পারে।"],
            "follow_ups": ["prevention", "platelets"]},
    },
    "community": {
        "keywords": ["community", "officer", "ward councillor", "health worker", "school", "campaign", "clean-up", "clean up", "building", "landlord", "apartment", "সমাজ", "কাউন্সিলর", "স্কুল", "অভিযান", "ভবন"],
        "en": {"title": "What communities and officers can do", "body": [
            "Weekly 'search and destroy' of breeding containers in every household, school, mosque, construction site and market (10 minutes, same day each week).",
            "Prioritise wards flagged High/Critical by the forecast: larviciding, drain and water-logging clearance, and inspecting construction sites first.",
            "Hospitals: prepare dengue beds, IV fluid, lab capacity and triage desks 1-3 weeks before the forecast peak.",
            "Risk communication: explain warning signs and 'do not take NSAIDs' in Bangla through mosques, schools, and mobile messages."],
            "follow_ups": ["actions", "season"]},
        "bn": {"title": "সম্প্রদায় ও কর্মকর্তারা কী করতে পারেন", "body": [
            "প্রতিটি বাড়ি, স্কুল, মসজিদ, নির্মাণস্থল ও বাজারে সাপ্তাহিক 'খুঁজে বের করে ধ্বংস করুন' (সপ্তাহে একই দিনে ১০ মিনিট)।",
            "পূর্বাভাসে উচ্চ/সংকটজনক চিহ্নিত ওয়ার্ডগুলোকে অগ্রাধিকার দিন: লার্ভিসাইডিং, ড্রেন ও জলাবদ্ধতা পরিষ্কার এবং আগে নির্মাণস্থল পরিদর্শন।",
            "হাসপাতাল: পূর্বাভাসের শীর্ষের ১-৩ সপ্তাহ আগে ডেঙ্গু বেড, আইভি স্যালাইন, ল্যাব সক্ষমতা ও ট্রায়াজ ডেস্ক প্রস্তুত রাখুন।",
            "ঝুঁকি-যোগাযোগ: মসজিদ, স্কুল ও মোবাইল বার্তায় বাংলায় সতর্কসংকেত এবং 'NSAID খাবেন না' বার্তা ছড়ান।"],
            "follow_ups": ["actions", "season"]},
    },
}

# ---------------------------------------------------------------------------
# Small-talk
# ---------------------------------------------------------------------------
SMALLTALK = {
    "greet": {
        "en": "Hello! I'm the Dengue Watch assistant. I can explain dengue (symptoms, warning signs, prevention, care), and use the forecasting models for Bangladesh wards: risk by city and ward, future seasons, rainfall what-ifs and model accuracy. What would you like to know?",
        "bn": "আসসালামু আলাইকুম! আমি ডেঙ্গু ওয়াচ সহকারী। ডেঙ্গুর লক্ষণ, সতর্কসংকেত, প্রতিরোধ ও যত্ন নিয়ে এবং আমাদের পূর্বাভাস মডেল থেকে শহর/ওয়ার্ডভিত্তিক ঝুঁকি, ভবিষ্যৎ মৌসুম, বৃষ্টির পরিস্থিতি ও মডেলের নির্ভুলতা নিয়ে সাহায্য করতে পারি। কী জানতে চান?",
    },
    "thanks": {"en": "You're welcome! Stay safe and keep water containers empty and covered.",
               "bn": "আপনাকে ধন্যবাদ! নিরাপদ থাকুন এবং পানির পাত্র খালি ও ঢাকা রাখুন।"},
    "bye": {"en": "Goodbye - stay safe, and see a doctor early if you develop a fever.",
            "bn": "বিদায় - সুস্থ থাকুন, জ্বর হলে আগেভাগে চিকিৎসকের কাছে যান।"},
    "about_bot": {
        "en": "I'm a dengue information assistant for the Dengue Watch dashboard. I combine WHO-aligned dengue guidance with this project's trained forecasting models (13 horizon models, 60 wards in 5 cities). I'm not a doctor and cannot diagnose; I'm a rule-based assistant, not a generative AI, so I may not understand unusual phrasing.",
        "bn": "আমি ডেঙ্গু ওয়াচ ড্যাশবোর্ডের তথ্য-সহকারী। আমি ডব্লিউএইচও-ভিত্তিক ডেঙ্গু নির্দেশনার সঙ্গে এই প্রকল্পের প্রশিক্ষিত পূর্বাভাস মডেল (১৩টি হরাইজন মডেল, ৫ শহরের ৬০টি ওয়ার্ড) ব্যবহার করি। আমি চিকিৎসক নই, রোগ নির্ণয় করতে পারি না; আমি নিয়মভিত্তিক সহকারী, জেনারেটিভ এআই নয়, তাই অস্বাভাবিক বাক্য নাও বুঝতে পারি।",
    },
    "fallback": {
        "en": "I'm not sure I understood that. I can help with dengue symptoms, warning signs, prevention and home care, and with forecasts such as 'risk in Dhaka North next 4 weeks', 'top wards in Gazipur', 'dengue in August 2026', or 'what if rainfall doubles'. Try one of these:",
        "bn": "আমি ঠিক বুঝতে পারিনি। আমি ডেঙ্গুর লক্ষণ, সতর্কসংকেত, প্রতিরোধ, বাসায় যত্ন এবং পূর্বাভাস (যেমন 'ঢাকা উত্তরে আগামী ৪ সপ্তাহের ঝুঁকি', 'গাজীপুরের শীর্ষ ওয়ার্ড', '২০২৬ সালের আগস্টে ডেঙ্গু') নিয়ে সাহায্য করতে পারি। এগুলো চেষ্টা করুন:",
    },
    "off_topic": {
        "en": "That's outside what I can help with - I focus on dengue and the Dengue Watch forecasts. Ask me about dengue symptoms, prevention, or ward-level risk.",
        "bn": "এটি আমার সাহায্যের বাইরে - আমি ডেঙ্গু ও ডেঙ্গু ওয়াচ পূর্বাভাস নিয়ে কাজ করি। ডেঙ্গুর লক্ষণ, প্রতিরোধ বা ওয়ার্ডভিত্তিক ঝুঁকি সম্পর্কে জিজ্ঞাসা করুন।",
    },
}

# Suggestion chips (label per language). key -> text sent as the user message.
SUGGESTIONS = {
    "en": ["What are the symptoms of dengue?", "Warning signs - when to go to hospital?", "How do I prevent dengue?",
           "Which wards in Dhaka North have the highest risk?", "Dengue risk next 4 weeks in Dhaka South",
           "When is dengue season?", "How accurate is the model?", "Forecast for August 2026"],
    "bn": ["ডেঙ্গুর লক্ষণ কী?", "কখন হাসপাতালে যেতে হবে?", "ডেঙ্গু প্রতিরোধের উপায় কী?",
           "ঢাকা উত্তরের কোন ওয়ার্ডে ঝুঁকি সবচেয়ে বেশি?", "ডেঙ্গুর মৌসুম কখন?", "মডেল কতটা নির্ভুল?"],
}

FOLLOW_UP_LABELS = {
    "en": {"symptoms": "Symptoms", "warning_signs": "Warning signs", "prevention": "Prevention", "home_care": "Home care",
           "testing": "Testing", "treatment": "Treatment", "diet": "Food & drink", "platelets": "Platelets", "transmission": "How it spreads",
           "breeding": "Breeding sites", "vaccine": "Vaccine", "season": "Dengue season", "rain_link": "Rain & weather link",
           "hotline": "Hotlines", "actions": "Action plan", "what_is": "What is dengue?"},
    "bn": {"symptoms": "লক্ষণ", "warning_signs": "সতর্ক চিহ্ন", "prevention": "প্রতিরোধ", "home_care": "বাসায় যত্ন",
           "testing": "পরীক্ষা", "treatment": "চিকিৎসা", "diet": "খাবার", "platelets": "প্লাটিলেট", "transmission": "কীভাবে ছড়ায়",
           "breeding": "প্রজননস্থল", "vaccine": "টিকা", "season": "ডেঙ্গুর মৌসুম", "rain_link": "বৃষ্টি ও আবহাওয়া",
           "hotline": "হটলাইন", "actions": "করণীয়", "what_is": "ডেঙ্গু কী?"},
}
