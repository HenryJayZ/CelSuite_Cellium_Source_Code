#!/usr/bin/env python3
"""Oxford / CMU-style phonetic G2P and ARPABET acoustic table.

Ported 1:1 from ``melodii_oxford_phonetic_studio_monochrome.html`` (the
Melodii & Oxford Phonetic Studio).  The HTML is the reference implementation
for **Cel's Realistic Voice**: the same phoneme mouth-shapes, the same Oxford
lexicon, the same silent-letter rules and the same morphological stemmer.
Keeping this module pure data + pure functions means the synthesiser can run
on a worker thread without touching Qt.

No third-party imports: this file is headless-testable and safe to import
from ``cellium.core``.
"""
from __future__ import annotations

import re
from typing import Iterable

#: ARPABET / IPA acoustic table - formant centres (Hz), bandwidth Q-ish,
#: amplitude and articulation flags for every phoneme.
PHONEMES = {
    'AA': {
        'f1': 750.0,
        'f2': 1180.0,
        'f3': 2540.0,
        'open': 0.9,
        'wide': 0.7,
        'isVowel': True,
        'dur': 1.15,
    },
    'AE': {
        'f1': 680.0,
        'f2': 1720.0,
        'f3': 2450.0,
        'open': 0.82,
        'wide': 0.85,
        'isVowel': True,
        'dur': 1.1,
    },
    'AH': {
        'f1': 620.0,
        'f2': 1220.0,
        'f3': 2500.0,
        'open': 0.65,
        'wide': 0.62,
        'isVowel': True,
        'dur': 0.95,
    },
    'AO': {
        'f1': 560.0,
        'f2': 880.0,
        'f3': 2520.0,
        'open': 0.72,
        'wide': 0.45,
        'isVowel': True,
        'dur': 1.15,
    },
    'AW': {
        'f1': 740.0,
        'f2': 1220.0,
        'f3': 2520.0,
        'f1End': 340.0,
        'f2End': 780.0,
        'f3End': 2360.0,
        'open': 0.88,
        'wide': 0.4,
        'isVowel': True,
        'dur': 1.35,
    },
    'AY': {
        'f1': 740.0,
        'f2': 1180.0,
        'f3': 2520.0,
        'f1End': 300.0,
        'f2End': 2220.0,
        'f3End': 2900.0,
        'open': 0.88,
        'wide': 0.9,
        'isVowel': True,
        'dur': 1.35,
    },
    'B': {
        'f1': 340.0,
        'f2': 1080.0,
        'f3': 2320.0,
        'open': 0.22,
        'wide': 0.52,
        'isVowel': False,
        'voicedCons': True,
        'plosive': True,
        'dur': 0.45,
        'noiseF': 950.0,
        'noiseG': 0.05,
    },
    'CH': {
        'f1': 350.0,
        'f2': 1960.0,
        'f3': 2740.0,
        'open': 0.35,
        'wide': 0.72,
        'isVowel': False,
        'voicedCons': False,
        'plosive': True,
        'dur': 0.54,
        'noiseF': 3200.0,
        'noiseG': 0.12,
    },
    'D': {
        'f1': 360.0,
        'f2': 1700.0,
        'f3': 2600.0,
        'open': 0.32,
        'wide': 0.7,
        'isVowel': False,
        'voicedCons': True,
        'plosive': True,
        'dur': 0.45,
        'noiseF': 2700.0,
        'noiseG': 0.06,
    },
    'DH': {
        'f1': 380.0,
        'f2': 1680.0,
        'f3': 2580.0,
        'open': 0.32,
        'wide': 0.68,
        'isVowel': False,
        'voicedCons': True,
        'dur': 0.52,
        'noiseF': 2600.0,
        'noiseG': 0.04,
    },
    'EH': {
        'f1': 530.0,
        'f2': 1840.0,
        'f3': 2480.0,
        'open': 0.62,
        'wide': 0.82,
        'isVowel': True,
        'dur': 1.0,
    },
    'ER': {
        'f1': 470.0,
        'f2': 1380.0,
        'f3': 1690.0,
        'open': 0.55,
        'wide': 0.52,
        'isVowel': True,
        'dur': 1.2,
    },
    'EY': {
        'f1': 510.0,
        'f2': 1900.0,
        'f3': 2520.0,
        'f1End': 290.0,
        'f2End': 2280.0,
        'f3End': 2950.0,
        'open': 0.68,
        'wide': 0.92,
        'isVowel': True,
        'dur': 1.3,
    },
    'F': {
        'f1': 400.0,
        'f2': 1300.0,
        'f3': 2400.0,
        'open': 0.24,
        'wide': 0.6,
        'isVowel': False,
        'voicedCons': False,
        'dur': 0.52,
        'noiseF': 2300.0,
        'noiseG': 0.09,
    },
    'G': {
        'f1': 390.0,
        'f2': 1480.0,
        'f3': 2420.0,
        'open': 0.4,
        'wide': 0.62,
        'isVowel': False,
        'voicedCons': True,
        'plosive': True,
        'dur': 0.45,
        'noiseF': 1800.0,
        'noiseG': 0.06,
    },
    'HH': {
        'f1': 580.0,
        'f2': 1550.0,
        'f3': 2520.0,
        'open': 0.58,
        'wide': 0.66,
        'isVowel': False,
        'voicedCons': False,
        'dur': 0.48,
        'noiseF': 1600.0,
        'noiseG': 0.09,
    },
    'IH': {
        'f1': 390.0,
        'f2': 1990.0,
        'f3': 2550.0,
        'open': 0.45,
        'wide': 0.86,
        'isVowel': True,
        'dur': 0.9,
    },
    'IY': {
        'f1': 280.0,
        'f2': 2290.0,
        'f3': 3010.0,
        'open': 0.35,
        'wide': 0.95,
        'isVowel': True,
        'dur': 1.15,
    },
    'JH': {
        'f1': 350.0,
        'f2': 1980.0,
        'f3': 2760.0,
        'open': 0.36,
        'wide': 0.76,
        'isVowel': False,
        'voicedCons': True,
        'plosive': True,
        'dur': 0.55,
        'noiseF': 2900.0,
        'noiseG': 0.11,
    },
    'K': {
        'f1': 410.0,
        'f2': 1450.0,
        'f3': 2400.0,
        'open': 0.4,
        'wide': 0.62,
        'isVowel': False,
        'voicedCons': False,
        'plosive': True,
        'dur': 0.44,
        'noiseF': 2150.0,
        'noiseG': 0.09,
    },
    'L': {
        'f1': 370.0,
        'f2': 1120.0,
        'f3': 2560.0,
        'open': 0.45,
        'wide': 0.64,
        'isVowel': False,
        'voicedCons': True,
        'glide': True,
        'dur': 0.6,
    },
    'M': {
        'f1': 270.0,
        'f2': 920.0,
        'f3': 2220.0,
        'open': 0.12,
        'wide': 0.54,
        'isVowel': False,
        'voicedCons': True,
        'nasal': True,
        'dur': 0.62,
    },
    'N': {
        'f1': 300.0,
        'f2': 1380.0,
        'f3': 2420.0,
        'open': 0.2,
        'wide': 0.62,
        'isVowel': False,
        'voicedCons': True,
        'nasal': True,
        'dur': 0.58,
    },
    'NG': {
        'f1': 290.0,
        'f2': 1920.0,
        'f3': 2550.0,
        'open': 0.25,
        'wide': 0.66,
        'isVowel': False,
        'voicedCons': True,
        'nasal': True,
        'dur': 0.65,
    },
    'OW': {
        'f1': 490.0,
        'f2': 920.0,
        'f3': 2480.0,
        'f1End': 320.0,
        'f2End': 740.0,
        'f3End': 2350.0,
        'open': 0.74,
        'wide': 0.38,
        'isVowel': True,
        'dur': 1.3,
    },
    'OY': {
        'f1': 520.0,
        'f2': 860.0,
        'f3': 2480.0,
        'f1End': 290.0,
        'f2End': 2240.0,
        'f3End': 2920.0,
        'open': 0.72,
        'wide': 0.88,
        'isVowel': True,
        'dur': 1.35,
    },
    'P': {
        'f1': 350.0,
        'f2': 1100.0,
        'f3': 2300.0,
        'open': 0.18,
        'wide': 0.5,
        'isVowel': False,
        'voicedCons': False,
        'plosive': True,
        'dur': 0.42,
        'noiseF': 1150.0,
        'noiseG': 0.08,
    },
    'R': {
        'f1': 410.0,
        'f2': 1280.0,
        'f3': 1660.0,
        'open': 0.48,
        'wide': 0.5,
        'isVowel': False,
        'voicedCons': True,
        'glide': True,
        'dur': 0.6,
    },
    'S': {
        'f1': 320.0,
        'f2': 1900.0,
        'f3': 2800.0,
        'open': 0.24,
        'wide': 0.8,
        'isVowel': False,
        'voicedCons': False,
        'dur': 0.54,
        'noiseF': 4800.0,
        'noiseG': 0.11,
    },
    'SH': {
        'f1': 340.0,
        'f2': 1980.0,
        'f3': 2680.0,
        'open': 0.34,
        'wide': 0.62,
        'isVowel': False,
        'voicedCons': False,
        'dur': 0.56,
        'noiseF': 3100.0,
        'noiseG': 0.12,
    },
    'T': {
        'f1': 360.0,
        'f2': 1750.0,
        'f3': 2650.0,
        'open': 0.28,
        'wide': 0.72,
        'isVowel': False,
        'voicedCons': False,
        'plosive': True,
        'dur': 0.42,
        'noiseF': 3600.0,
        'noiseG': 0.09,
    },
    'TH': {
        'f1': 400.0,
        'f2': 1720.0,
        'f3': 2650.0,
        'open': 0.32,
        'wide': 0.68,
        'isVowel': False,
        'voicedCons': False,
        'dur': 0.55,
        'noiseF': 3800.0,
        'noiseG': 0.09,
    },
    'UH': {
        'f1': 440.0,
        'f2': 1020.0,
        'f3': 2380.0,
        'open': 0.48,
        'wide': 0.45,
        'isVowel': True,
        'dur': 0.9,
    },
    'UW': {
        'f1': 310.0,
        'f2': 850.0,
        'f3': 2350.0,
        'f1End': 290.0,
        'f2End': 720.0,
        'f3End': 2300.0,
        'open': 0.38,
        'wide': 0.3,
        'isVowel': True,
        'dur': 1.2,
    },
    'V': {
        'f1': 370.0,
        'f2': 1240.0,
        'f3': 2400.0,
        'open': 0.26,
        'wide': 0.58,
        'isVowel': False,
        'voicedCons': True,
        'dur': 0.52,
        'noiseF': 1850.0,
        'noiseG': 0.08,
    },
    'W': {
        'f1': 290.0,
        'f2': 620.0,
        'f3': 2180.0,
        'open': 0.3,
        'wide': 0.28,
        'isVowel': False,
        'voicedCons': True,
        'glide': True,
        'dur': 0.58,
    },
    'Y': {
        'f1': 280.0,
        'f2': 2180.0,
        'f3': 2920.0,
        'open': 0.36,
        'wide': 0.9,
        'isVowel': False,
        'voicedCons': True,
        'glide': True,
        'dur': 0.55,
    },
    'Z': {
        'f1': 320.0,
        'f2': 1880.0,
        'f3': 2800.0,
        'open': 0.26,
        'wide': 0.78,
        'isVowel': False,
        'voicedCons': True,
        'dur': 0.55,
        'noiseF': 4200.0,
        'noiseG': 0.1,
    },
    'ZH': {
        'f1': 340.0,
        'f2': 1960.0,
        'f3': 2660.0,
        'open': 0.34,
        'wide': 0.64,
        'isVowel': False,
        'voicedCons': True,
        'dur': 0.56,
        'noiseF': 3000.0,
        'noiseG': 0.1,
    },
}

#: Oxford core + irregular English dictionary. Values are space-separated
#: ARPABET tokens with optional stress digits (0/1/2).
LEXICON = {
    'ACHE': 'EY1 K',
    'AESTHETIC': 'EH0 S TH EH1 T IH0 K',
    'AGAIN': 'AH0 G EH1 N',
    'AISLE': 'AY1 L',
    'AISLES': 'AY1 L Z',
    'ALIGN': 'AH0 L AY1 N',
    'ALLEY': 'AE1 L IY0',
    'ALMOND': 'AA1 M AH0 N D',
    'ALTHOUGH': 'AO2 L DH OW1',
    'AM': 'AE1 M',
    'AMOEOBA': 'AH0 M IY1 B AH0',
    'ANALYZE': 'AE1 N AH0 L AY2 Z',
    'ANARCHY': 'AE1 N ER0 K IY0',
    'ANCHOR': 'AE1 NG K ER0',
    'ANCIENT': 'EY1 N SH AH0 N T',
    'ANEMONE': 'AH0 N EH1 M AH0 N IY0',
    'ANOTHER': 'AH0 N AH1 DH ER0',
    'ANSWER': 'AE1 N S ER0',
    'ANSWERED': 'AE1 N S ER0 D',
    'ANSWERS': 'AE1 N S ER0 Z',
    'ANTIQUE': 'AE0 N T IY1 K',
    'ANXIOUS': 'AE1 NG K SH AH0 S',
    'APOSTLE': 'AH0 P AA1 S AH0 L',
    'APOSTROPHE': 'AH0 P AA1 S T R AH0 F IY0',
    'ARCHITECT': 'AA1 R K AH0 T EH2 K T',
    'ARCHITECTURE': 'AA1 R K AH0 T EH2 K CH ER0',
    'ARCHIVE': 'AA1 R K AY2 V',
    'ARCHIVES': 'AA1 R K AY2 V Z',
    'ARE': 'AA1 R',
    'ARTIFICIAL': 'AA2 R T AH0 F IH1 SH AH0 L',
    'AS': 'AE1 Z',
    'ASCEND': 'AH0 S EH1 N D',
    'ASIA': 'EY1 ZH AH0',
    'ASSIGN': 'AH0 S AY1 N',
    'ATTORNEY': 'AH0 T ER1 N IY0',
    'AUTUMN': 'AO1 T AH0 M',
    'BALLET': 'B AE0 L EY1',
    'BALM': 'B AA1 M',
    'BEACH': 'B IY1 CH',
    'BEAUTIFUL': 'B Y UW1 T AH0 F AH0 L',
    'BEAUTY': 'B Y UW1 T IY0',
    'BEHALF': 'B IH0 HH AE1 F',
    'BEIGE': 'B EY1 ZH',
    'BENIGN': 'B IH0 N AY1 N',
    'BISCUIT': 'B IH1 S K AH0 T',
    'BLOOD': 'B L AH1 D',
    'BOLOGNA': 'B AH0 L OW1 N IY0',
    'BOMB': 'B AA1 M',
    'BOMBS': 'B AA1 M Z',
    'BOROUGH': 'B ER1 OW0',
    'BOSOM': 'B UH1 Z AH0 M',
    'BOUGH': 'B AW1',
    'BOUGHT': 'B AO1 T',
    'BOUQUET': 'B OW0 K EY1',
    'BOURGEOIS': 'B UH1 R ZH W AA2',
    'BOUTIQUE': 'B UW0 T IY1 K',
    'BRO': 'B R OW1',
    'BROCCOLI': 'B R AA1 K AH0 L IY0',
    'BROCHURE': 'B R OW0 SH UH1 R',
    'BROTHER': 'B R AH1 DH ER0',
    'BUFFET': 'B AH0 F EY1',
    'BUILD': 'B IH1 L D',
    'BUILDING': 'B IH1 L D IH0 NG',
    'BUILDS': 'B IH1 L D Z',
    'BUILT': 'B IH1 L T',
    'BULL': 'B UH1 L',
    'BURIED': 'B EH1 R IY0 D',
    'BURY': 'B EH1 R IY0',
    'BUSH': 'B UH1 SH',
    'BUSINESS': 'B IH1 Z N AH0 S',
    'BUSTLE': 'B AH1 S AH0 L',
    'BUSY': 'B IH1 Z IY0',
    'BUY': 'B AY1',
    'BUYS': 'B AY1 Z',
    'BY': 'B AY1',
    'CACHET': 'K AE0 SH EY1',
    'CAFE': 'K AE0 F EY1',
    'CALF': 'K AE1 F',
    'CALM': 'K AA1 M',
    'CAMOUFLAGE': 'K AE1 M AH0 F L AA2 ZH',
    'CAMPAIGN': 'K AE0 M P EY1 N',
    'CASTLE': 'K AE1 S AH0 L',
    'CASTLES': 'K AE1 S AH0 L Z',
    'CASUAL': 'K AE1 ZH UW0 AH0 L',
    'CATALOGUE': 'K AE1 T AH0 L AO0 G',
    'CATASTROPHE': 'K AH0 T AE1 S T R AH0 F IY0',
    'CEILING': 'S IY1 L IH0 NG',
    'CHALET': 'SH AE0 L EY1',
    'CHALK': 'CH AO1 K',
    'CHAMPAGNE': 'SH AE0 M P EY1 N',
    'CHANDELIER': 'SH AE2 N D AH0 L IH1 R',
    'CHAOS': 'K EY1 AA0 S',
    'CHARADE': 'SH ER0 EY1 D',
    'CHARISMA': 'K ER0 IH1 Z M AH0',
    'CHASM': 'K AE1 Z AH0 M',
    'CHAUFFEUR': 'SH OW1 F ER0',
    'CHEF': 'SH EH1 F',
    'CHEMICAL': 'K EH1 M IH0 K AH0 L',
    'CHEMIST': 'K EH1 M AH0 S T',
    'CHEMISTRY': 'K EH1 M AH0 S T R IY0',
    'CHIVALRY': 'SH IH1 V AH0 L R IY0',
    'CHOCOLATE': 'CH AO1 K L AH0 T',
    'CHOIR': 'K W AY1 ER0',
    'CHOIRS': 'K W AY1 ER0 Z',
    'CHORD': 'K AO1 R D',
    'CHORDS': 'K AO1 R D Z',
    'CHORUS': 'K AO1 R AH0 S',
    'CHRISTMAS': 'K R IH1 S M AH0 S',
    'CIRCUIT': 'S ER1 K AH0 T',
    'CLICHE': 'K L IY0 SH EY1',
    'CLIMB': 'K L AY1 M',
    'CLIMBED': 'K L AY1 M D',
    'CLIMBER': 'K L AY1 M ER0',
    'CLIMBING': 'K L AY1 M IH0 NG',
    'CLIMBS': 'K L AY1 M Z',
    'CLOSURE': 'K L OW1 ZH ER0',
    'CLOUDS': 'K L AW1 D Z',
    'COLLEAGUE': 'K AA1 L IY0 G',
    'COLOGNE': 'K AH0 L OW1 N',
    'COLONEL': 'K ER1 N AH0 L',
    'COLUMN': 'K AA1 L AH0 M',
    'COLUMNS': 'K AA1 L AH0 M Z',
    'COMB': 'K OW1 M',
    'COME': 'K AH1 M',
    'COMFORTABLE': 'K AH1 M F T ER0 B AH0 L',
    'COMMERCIAL': 'K AH0 M ER1 SH AH0 L',
    'CONCEIVE': 'K AH0 N S IY1 V',
    'CONDEMN': 'K AH0 N D EH1 M',
    'CONFETTI': 'K AH0 N F EH1 T IY0',
    'CONFUSION': 'K AH0 N F Y UW1 ZH AH0 N',
    'CONQUER': 'K AA1 NG K ER0',
    'CONSCIENCE': 'K AA1 N SH AH0 N S',
    'CONSCIOUS': 'K AA1 N SH AH0 S',
    'CONVEY': 'K AH0 N V EY1',
    'CORPS': 'K AO1 R',
    'COUGH': 'K AO1 F',
    'COUGHS': 'K AO1 F S',
    'COULD': 'K UH1 D',
    'COUP': 'K UW1',
    'CRESCENT': 'K R EH1 S AH0 N T',
    'CRITIQUE': 'K R IH0 T IY1 K',
    'CROCHET': 'K R OW0 SH EY1',
    'CROISSANT': 'K R W AA0 S AA1 N',
    'CRUMB': 'K R AH1 M',
    'CRY': 'K R AY1',
    'CRYPT': 'K R IH1 P T',
    'CRYSTAL': 'K R IH1 S T AH0 L',
    'CUPBOARD': 'K AH1 B ER0 D',
    'CYBER': 'S AY1 B ER0',
    'CYCLE': 'S AY1 K AH0 L',
    'CYNICAL': 'S IH1 N IH0 K AH0 L',
    'DAMN': 'D AE1 M',
    'DEBRIS': 'D AH0 B R IY1',
    'DEBT': 'D EH1 T',
    'DEBTOR': 'D EH1 T ER0',
    'DEBTS': 'D EH1 T S',
    'DEBUT': 'D EY1 B Y UW0',
    'DECEIVE': 'D IH0 S IY1 V',
    'DECISION': 'D IH0 S IH1 ZH AH0 N',
    'DELICIOUS': 'D IH0 L IH1 SH AH0 S',
    'DESCEND': 'D IH0 S EH1 N D',
    'DESIGN': 'D IH0 Z AY1 N',
    'DESIGNED': 'D IH0 Z AY1 N D',
    'DIALOGUE': 'D AY1 AH0 L AO0 G',
    'DISCIPLE': 'D IH0 S AY1 P AH0 L',
    'DISGUISE': 'D IH0 S G AY1 Z',
    'DO': 'D UW1',
    'DONKEY': 'D AA1 NG K IY0',
    'DOOR': 'D AO1 R',
    'DOUBT': 'D AW1 T',
    'DOUBTFUL': 'D AW1 T F AH0 L',
    'DOUBTS': 'D AW1 T S',
    'DOUGH': 'D OW1',
    'DOWN': 'D AW1 N',
    'DROUGHT': 'D R AW1 T',
    'DRY': 'D R AY1',
    'DUMB': 'D AH1 M',
    'DYNAMIC': 'D AY0 N AE1 M IH0 K',
    'ECHO': 'EH1 K OW0',
    'EFFICIENT': 'IH0 F IH1 SH AH0 N T',
    'EIGHT': 'EY1 T',
    'EIGHTEEN': 'EY0 T IY1 N',
    'EIGHTH': 'EY1 T TH',
    'EIGHTY': 'EY1 T IY0',
    'ENOUGH': 'IH0 N AH1 F',
    'ENTREE': 'AA1 N T R EY2',
    'EPITOME': 'IH0 P IH1 T AH0 M IY0',
    'EPOCH': 'EH1 P AH0 K',
    'ESPECIALLY': 'AH0 S P EH1 SH L IY0',
    'EXPOSURE': 'IH0 K S P OW1 ZH ER0',
    'EYE': 'AY1',
    'EYES': 'AY1 Z',
    'FASCINATE': 'F AE1 S AH0 N EY2 T',
    'FASCINATING': 'F AE1 S AH0 N EY2 T IH0 NG',
    'FASTEN': 'F AE1 S AH0 N',
    'FAT': 'F AE1 T',
    'FATHER': 'F AA1 DH ER0',
    'FATIGUE': 'F AH0 T IY1 G',
    'FAUX': 'F OW1',
    'FEBRUARY': 'F EH1 B Y UW0 EH2 R IY0',
    'FIANCE': 'F IY2 AA0 N S EY1',
    'FINALE': 'F AH0 N AE1 L IY0',
    'FINANCIAL': 'F AH0 N AE1 N SH AH0 L',
    'FLOATING': 'F L OW1 T IH0 NG',
    'FLOOD': 'F L AH1 D',
    'FLOOR': 'F L AO1 R',
    'FLY': 'F L AY1',
    'FOLK': 'F OW1 K',
    'FOLKS': 'F OW1 K S',
    'FOREIGN': 'F AO1 R AH0 N',
    'FOREIGNER': 'F AO1 R AH0 N ER0',
    'FREIGHT': 'F R EY1 T',
    'FRIEND': 'F R EH1 N D',
    'FRIENDS': 'F R EH1 N D Z',
    'FULL': 'F UH1 L',
    'GARAGE': 'G ER0 AA1 ZH',
    'GEMINI': 'JH EH1 M AH0 N AY2',
    'GENRE': 'ZH AA1 N R AH0',
    'GLISTEN': 'G L IH1 S AH0 N',
    'GNAT': 'N AE1 T',
    'GNAW': 'N AO1',
    'GNOME': 'N OW1 M',
    'GO': 'G OW1',
    'GOLDEN': 'G OW1 L D AH0 N',
    'GOURMET': 'G UH0 R M EY1',
    'GRAFFITI': 'G R AH0 F IY1 T IY0',
    'GRAY': 'G R EY1',
    'GREY': 'G R EY1',
    'GUARANTEE': 'G EH2 R AH0 N T IY1',
    'GUARD': 'G AA1 R D',
    'GUESS': 'G EH1 S',
    'GUEST': 'G EH1 S T',
    'GUESTS': 'G EH1 S T S',
    'GUIDE': 'G AY1 D',
    'GUIDES': 'G AY1 D Z',
    'GUILT': 'G IH1 L T',
    'GUILTY': 'G IH1 L T IY0',
    'GUITAR': 'G IH0 T AA1 R',
    'GUY': 'G AY1',
    'GUYS': 'G AY1 Z',
    'GYM': 'JH IH1 M',
    'HALF': 'HH AE1 F',
    'HALLELUJAH': 'HH AE2 L AH0 L UW1 Y AH0',
    'HALVES': 'HH AE1 V Z',
    'HAS': 'HH AE1 Z',
    'HEADACHE': 'HH EH1 D EY2 K',
    'HEAVEN': 'HH EH1 V AH0 N',
    'HEAVENLY': 'HH EH1 V AH0 N L IY0',
    'HEIGHT': 'HH AY1 T',
    'HEIGHTS': 'HH AY1 T S',
    'HEIR': 'EH1 R',
    'HEIRESS': 'EH1 R AH0 S',
    'HELLO': 'HH EH0 L OW1',
    'HEY': 'HH EY1',
    'HI': 'HH AY1',
    'HIERARCHY': 'HH AY1 ER0 AA2 R K IY0',
    'HIGH': 'HH AY1',
    'HIS': 'HH IH1 Z',
    'HONEY': 'HH AH1 N IY0',
    'HORSES': 'HH AO1 R S IH0 Z',
    'HOW': 'HH AW1',
    'HUSTLE': 'HH AH1 S AH0 L',
    'HYBRID': 'HH AY1 B R AH0 D',
    'HYDROGEN': 'HH AY1 D R AH0 JH AH0 N',
    'HYGIENE': 'HH AY1 JH IY2 N',
    'HYMN': 'HH IH1 M',
    'HYMNAL': 'HH IH1 M N AH0 L',
    'HYMNS': 'HH IH1 M Z',
    'HYPERBOLE': 'HH AY0 P ER1 B AH0 L IY0',
    'HYPHEN': 'HH AY1 F AH0 N',
    'I': 'AY1',
    'ID': 'AY1 D',
    'ILL': 'AY1 L',
    'ILLUSION': 'IH0 L UW1 ZH AH0 N',
    'IM': 'AY1 M',
    'INDICT': 'IH0 N D AY1 T',
    'INDICTED': 'IH0 N D AY1 T AH0 D',
    'INDICTMENT': 'IH0 N D AY1 T M AH0 N T',
    'INTERVIEW': 'IH1 N T ER0 V Y UW2',
    'INTRIGUE': 'IH0 N T R IY1 G',
    'IRON': 'AY1 ER0 N',
    'IRONY': 'AY1 R AH0 N IY0',
    'IS': 'IH1 Z',
    'ISLAND': 'AY1 L AH0 N D',
    'ISLANDS': 'AY1 L AH0 N D Z',
    'ISLE': 'AY1 L',
    'IVE': 'AY1 V',
    'JALAPENO': 'HH AA2 L AH0 P EY1 N Y OW0',
    'JEOPARDY': 'JH EH1 P ER0 D IY0',
    'JOURNEY': 'JH ER1 N IY0',
    'KARAOKE': 'K EH2 R IY0 OW1 K IY0',
    'KEY': 'K IY1',
    'KEYS': 'K IY1 Z',
    'KNEE': 'N IY1',
    'KNEEL': 'N IY1 L',
    'KNEES': 'N IY1 Z',
    'KNEW': 'N UW1',
    'KNIFE': 'N AY1 F',
    'KNIGHT': 'N AY1 T',
    'KNIGHTS': 'N AY1 T S',
    'KNIT': 'N IH1 T',
    'KNIVES': 'N AY1 V Z',
    'KNOCK': 'N AA1 K',
    'KNOT': 'N AA1 T',
    'KNOW': 'N OW1',
    'KNOWLEDGE': 'N AA1 L AH0 JH',
    'KNOWN': 'N OW1 N',
    'KNOWS': 'N OW1 Z',
    'KNUCKLE': 'N AH1 K AH0 L',
    'LAMB': 'L AE1 M',
    'LASAGNA': 'L AH0 Z AA1 N Y AH0',
    'LAUGH': 'L AE1 F',
    'LAUGHED': 'L AE1 F T',
    'LAUGHING': 'L AE1 F IH0 NG',
    'LAUGHS': 'L AE1 F S',
    'LAUGHTER': 'L AE1 F T ER0',
    'LEAGUE': 'L IY1 G',
    'LEISURE': 'L IY1 ZH ER0',
    'LEOPARD': 'L EH1 P ER0 D',
    'LET': 'L EH1 T',
    'LETS': 'L EH1 T S',
    'LETTUCE': 'L EH1 T AH0 S',
    'LIBRARY': 'L AY1 B R EH2 R IY0',
    'LIEUTENANT': 'L UW0 T EH1 N AH0 N T',
    'LIGHT': 'L AY1 T',
    'LIMB': 'L IH1 M',
    'LIQUOR': 'L IH1 K ER0',
    'LISTEN': 'L IH1 S AH0 N',
    'LISTENED': 'L IH1 S AH0 N D',
    'LISTENING': 'L IH1 S AH0 N IH0 NG',
    'LISTENS': 'L IH1 S AH0 N Z',
    'LOVE': 'L AH1 V',
    'LOVED': 'L AH1 V D',
    'LYNX': 'L IH1 NG K S',
    'LYRIC': 'L IH1 R IH0 K',
    'LYRICS': 'L IH1 R IH0 K S',
    'MACHINE': 'M AH0 SH IY1 N',
    'MACHINERY': 'M AH0 SH IY1 N ER0 IY0',
    'MACHINES': 'M AH0 SH IY1 N Z',
    'MAGIC': 'M AE1 JH IH0 K',
    'MAGICIAN': 'M AH0 JH IH1 SH AH0 N',
    'MASSAGE': 'M AH0 S AA1 ZH',
    'MEASURE': 'M EH1 ZH ER0',
    'MECHANIC': 'M AH0 K AE1 N IH0 K',
    'MECHANICAL': 'M AH0 K AE1 N IH0 K AH0 L',
    'MELODII': 'M EH1 L OW0 D IY1',
    'MELODY': 'M EH1 L AH0 D IY0',
    'MINUTE': 'M IH1 N AH0 T',
    'MINUTES': 'M IH1 N AH0 T S',
    'MIRAGE': 'M IH0 R AA1 ZH',
    'MOISTEN': 'M OY1 S AH0 N',
    'MONARCH': 'M AA1 N AA0 R K',
    'MONEY': 'M AH1 N IY0',
    'MONKEY': 'M AH1 NG K IY0',
    'MORTGAGE': 'M AO1 R G IH0 JH',
    'MOSQUE': 'M AA1 S K',
    'MOTHER': 'M AH1 DH ER0',
    'MUSCLE': 'M AH1 S AH0 L',
    'MUSCLES': 'M AH1 S AH0 L Z',
    'MUSIC': 'M Y UW1 Z IH0 K',
    'MUSICIAN': 'M Y UW0 Z IH1 SH AH0 N',
    'MUSTACHE': 'M AH1 S T AE2 SH',
    'MY': 'M AY1',
    'MYSTERY': 'M IH1 S T ER0 IY0',
    'MYSTIC': 'M IH1 S T IH0 K',
    'MYSTIQUE': 'M IH0 S T IY1 K',
    'MYTH': 'M IH1 TH',
    'MYTHS': 'M IH1 TH S',
    'NAIVE': 'N AA0 IY1 V',
    'NEIGHBOR': 'N EY1 B ER0',
    'NEIGHBORHOOD': 'N EY1 B ER0 HH UH2 D',
    'NEIGHBORS': 'N EY1 B ER0 Z',
    'NIGHT': 'N AY1 T',
    'NO': 'N OW1',
    'NOSTALGIA': 'N AA0 S T AE1 L JH AH0',
    'NOW': 'N AW1',
    'NUMB': 'N AH1 M',
    'NYMPH': 'N IH1 M F',
    'OBEY': 'OW0 B EY1',
    'OCEAN': 'OW1 SH AH0 N',
    'OCEANS': 'OW1 SH AH0 N Z',
    'OF': 'AH0 V',
    'OFFICIAL': 'AH0 F IH1 SH AH0 L',
    'OFTEN': 'AO1 F AH0 N',
    'OKAY': 'OW2 K EY1',
    'ONE': 'W AH1 N',
    'OPAQUE': 'OW0 P EY1 K',
    'ORCHESTRA': 'AO1 R K AH0 S T R AH0',
    'ORCHID': 'AO1 R K AH0 D',
    'ORIGAMI': 'AO2 R AH0 G AA1 M IY0',
    'OTHER': 'AH1 DH ER0',
    'OXYGEN': 'AA1 K S AH0 JH AH0 N',
    'PALM': 'P AA1 M',
    'PARACHUTE': 'P EH1 R AH0 SH UW2 T',
    'PARALYZE': 'P EH1 R AH0 L AY2 Z',
    'PATIENCE': 'P EY1 SH AH0 N S',
    'PATIENT': 'P EY1 SH AH0 N T',
    'PEOPLE': 'P IY1 P AH0 L',
    'PERCEIVE': 'P ER0 S IY1 V',
    'PHOENIX': 'F IY1 N IH0 K S',
    'PHYSICAL': 'F IH1 Z IH0 K AH0 L',
    'PHYSICIAN': 'F AH0 Z IH1 SH AH0 N',
    'PHYSICS': 'F IH1 Z IH0 K S',
    'PHYSIQUE': 'F IH0 Z IY1 K',
    'PISTACHIO': 'P IH0 S T AE1 SH IY0 OW2',
    'PLAGUE': 'P L EY1 G',
    'PLAQUE': 'P L AE1 K',
    'PLAY': 'P L EY1',
    'PLAYED': 'P L EY1 D',
    'PLEASE': 'P L IY1 Z',
    'PLEASURE': 'P L EH1 ZH ER0',
    'PLOUGH': 'P L AW1',
    'PLUMBER': 'P L AH1 M ER0',
    'PLUMBING': 'P L AH1 M IH0 NG',
    'PNEUMONIA': 'N UW0 M OW1 N Y AH0',
    'POLITICIAN': 'P AA2 L AH0 T IH1 SH AH0 N',
    'POOR': 'P UH1 R',
    'PRECIOUS': 'P R EH1 SH AH0 S',
    'PRECISION': 'P R IH0 S IH1 ZH AH0 N',
    'PRESTIGE': 'P R EH0 S T IY1 ZH',
    'PREY': 'P R EY1',
    'PSALM': 'S AA1 M',
    'PSALMS': 'S AA1 M Z',
    'PSEUDO': 'S UW1 D OW0',
    'PSYCHIATRIST': 'S AY0 K AY1 AH0 T R AH0 S T',
    'PSYCHIC': 'S AY1 K IH0 K',
    'PSYCHO': 'S AY1 K OW0',
    'PSYCHOLOGIST': 'S AY0 K AA1 L AH0 JH AH0 S T',
    'PSYCHOLOGY': 'S AY2 K AA1 L AH0 JH IY0',
    'PTERODACTYL': 'T EH2 R AH0 D AE1 K T AH0 L',
    'PULL': 'P UH1 L',
    'PURE': 'P Y UH1 R',
    'PUSH': 'P UH1 SH',
    'PUT': 'P UH1 T',
    'PYRAMID': 'P IH1 R AH0 M IH0 D',
    'PYTHON': 'P AY1 TH AA2 N',
    'QUESADILLA': 'K EY2 S AH0 D IY1 Y AH0',
    'QUEUE': 'K Y UW1',
    'QUEUES': 'K Y UW1 Z',
    'QUIET': 'K W AY1 AH0 T',
    'QUITE': 'K W AY1 T',
    'RASPBERRY': 'R AE1 Z B EH2 R IY0',
    'RECEIPT': 'R IH0 S IY1 T',
    'RECEIPTS': 'R IH0 S IY1 T S',
    'RECEIVE': 'R IH0 S IY1 V',
    'RECEIVED': 'R IH0 S IY1 V D',
    'RECIPE': 'R EH1 S AH0 P IY0',
    'RECIPES': 'R EH1 S AH0 P IY0 Z',
    'REGIME': 'R AH0 ZH IY1 M',
    'REIGN': 'R EY1 N',
    'REIN': 'R EY1 N',
    'RENDEZVOUS': 'R AA1 N D EY0 V UW2',
    'RESIGN': 'R IH0 Z AY1 N',
    'RESUME': 'R EH1 Z AH0 M EY2',
    'REVIEW': 'R IY0 V Y UW1',
    'RHYME': 'R AY1 M',
    'RHYMES': 'R AY1 M Z',
    'RHYTHM': 'R IH1 DH AH0 M',
    'RICOCHET': 'R IH1 K AH0 SH EY2',
    'RIGHT': 'R AY1 T',
    'ROGUE': 'R OW1 G',
    'ROUGH': 'R AH1 F',
    'RUNNING': 'R AH1 N IH0 NG',
    'RUSTLE': 'R AH1 S AH0 L',
    'SALMON': 'S AE1 M AH0 N',
    'SCENE': 'S IY1 N',
    'SCENERY': 'S IY1 N ER0 IY0',
    'SCENT': 'S EH1 N T',
    'SCHEDULE': 'S K EH1 JH UW0 L',
    'SCHEDULES': 'S K EH1 JH UW0 L Z',
    'SCHEME': 'S K IY1 M',
    'SCHOLAR': 'S K AA1 L ER0',
    'SCHOLARSHIP': 'S K AA1 L ER0 SH IH2 P',
    'SCHOOL': 'S K UW1 L',
    'SCHOOLS': 'S K UW1 L Z',
    'SCIENCE': 'S AY1 AH0 N S',
    'SCIENTIFIC': 'S AY2 AH0 N T IH1 F IH0 K',
    'SCIENTIST': 'S AY1 AH0 N T AH0 S T',
    'SCISSORS': 'S IH1 Z ER0 Z',
    'SCRATCHING': 'S K R AE1 CH IH0 NG',
    'SECRETARY': 'S EH1 K R AH0 T EH2 R IY0',
    'SEIZE': 'S IY1 Z',
    'SERGEANT': 'S AA1 R JH AH0 N T',
    'SEVEN': 'S EH1 V AH0 N',
    'SHOULD': 'SH UH1 D',
    'SHY': 'SH AY1',
    'SIGN': 'S AY1 N',
    'SIGNED': 'S AY1 N D',
    'SIGNS': 'S AY1 N Z',
    'SIMILE': 'S IH1 M AH0 L IY0',
    'SKY': 'S K AY1',
    'SLEIGH': 'S L EY1',
    'SLOUGH': 'S L AW1',
    'SO': 'S OW1',
    'SOCIAL': 'S OW1 SH AH0 L',
    'SOFTEN': 'S AO1 F AH0 N',
    'SOLDIER': 'S OW1 L JH ER0',
    'SOLDIERS': 'S OW1 L JH ER0 Z',
    'SOLEMN': 'S AA1 L AH0 M',
    'SOME': 'S AH1 M',
    'SOVEREIGN': 'S AA1 V R AH0 N',
    'SPAGHETTI': 'S P AH0 G EH1 T IY0',
    'SPECIAL': 'S P EH1 SH AH0 L',
    'STALK': 'S T AO1 K',
    'STOMACH': 'S T AH1 M AH0 K',
    'STYLE': 'S T AY1 L',
    'STYLES': 'S T AY1 L Z',
    'SUBPOENA': 'S AH0 P IY1 N AH0',
    'SUBTLE': 'S AH1 T AH0 L',
    'SUBTLY': 'S AH1 T L IY0',
    'SUFFICIENT': 'S AH0 F IH1 SH AH0 N T',
    'SUGAR': 'SH UH1 G ER0',
    'SURE': 'SH UH1 R',
    'SURVEY': 'S ER1 V EY2',
    'SUSPICIOUS': 'S AH0 S P IH1 SH AH0 S',
    'SWORD': 'S AO1 R D',
    'SWORDS': 'S AO1 R D Z',
    'SYMBOL': 'S IH1 M B AH0 L',
    'SYMPATHY': 'S IH1 M P AH0 TH IY0',
    'SYMPHONY': 'S IH1 M F AH0 N IY0',
    'SYMPTOM': 'S IH1 M P T AH0 M',
    'SYNTHESIS': 'S IH1 N TH AH0 S AH0 S',
    'SYNTHESIZER': 'S IH1 N TH AH0 S AY2 Z ER0',
    'SYRUP': 'S IH1 R AH0 P',
    'SYSTEM': 'S IH1 S T AH0 M',
    'SYSTEMS': 'S IH1 S T AH0 M Z',
    'TALK': 'T AO1 K',
    'TALKED': 'T AO1 K T',
    'TALKING': 'T AO1 K IH0 NG',
    'TECHNIQUE': 'T EH0 K N IY1 K',
    'TELEVISION': 'T EH1 L AH0 V IH2 ZH AH0 N',
    'THAN': 'DH AE1 N',
    'THAT': 'DH AE1 T',
    'THE': 'DH AH0',
    'THEIR': 'DH EH1 R',
    'THEM': 'DH EH1 M',
    'THEN': 'DH EH1 N',
    'THERE': 'DH EH1 R',
    'THESE': 'DH IY1 Z',
    'THEY': 'DH EY1',
    'THING': 'TH IH1 NG',
    'THINGS': 'TH IH1 NG Z',
    'THINK': 'TH IH1 NG K',
    'THIS': 'DH IH1 S',
    'THISTLE': 'TH IH1 S AH0 L',
    'THOROUGH': 'TH ER1 OW0',
    'THOSE': 'DH OW1 Z',
    'THOUGH': 'DH OW1',
    'THOUGHT': 'TH AO1 T',
    'THROUGH': 'TH R UW1',
    'THUMB': 'TH AH1 M',
    'THUMBS': 'TH AH1 M Z',
    'THYME': 'T AY1 M',
    'TO': 'T UW0',
    'TODAY': 'T AH0 D EY1',
    'TOGETHER': 'T AH0 G EH1 DH ER0',
    'TOMB': 'T UW1 M',
    'TONGUE': 'T AH1 NG',
    'TONIGHT': 'T AH0 N AY1 T',
    'TORTILLA': 'T AO0 R T IY1 Y AH0',
    'TOUGH': 'T AH1 F',
    'TREASURE': 'T R EH1 ZH ER0',
    'TROUGH': 'T R AO1 F',
    'TRY': 'T R AY1',
    'TSUNAMI': 'S UW0 N AA1 M IY0',
    'TWO': 'T UW1',
    'TYPE': 'T AY1 P',
    'TYPES': 'T AY1 P S',
    'TYPHOON': 'T AY0 F UW1 N',
    'TYPICAL': 'T IH1 P IH0 K AH0 L',
    'TYRANT': 'T AY1 R AH0 N T',
    'UNIQUE': 'Y UW0 N IY1 K',
    'USUAL': 'Y UW1 ZH UW0 AH0 L',
    'USUALLY': 'Y UW1 ZH UW0 AH0 L IY0',
    'VAGUE': 'V EY1 G',
    'VALET': 'V AE0 L EY1',
    'VALLEY': 'V AE1 L IY0',
    'VEGETABLE': 'V EH1 JH T AH0 B AH0 L',
    'VEGETABLES': 'V EH1 JH T AH0 B AH0 L Z',
    'VEIL': 'V EY1 L',
    'VEIN': 'V EY1 N',
    'VEINS': 'V EY1 N Z',
    'VERSION': 'V ER1 ZH AH0 N',
    'VIEW': 'V Y UW1',
    'VISCOUNT': 'V AY1 K AW2 N T',
    'VISION': 'V IH1 ZH AH0 N',
    'VISUAL': 'V IH1 ZH UW0 AH0 L',
    'VOGUE': 'V OW1 G',
    'WALK': 'W AO1 K',
    'WALKED': 'W AO1 K T',
    'WALKING': 'W AO1 K IH0 NG',
    'WARM': 'W AO1 R M',
    'WAS': 'W AA1 Z',
    'WEATHER': 'W EH1 DH ER0',
    'WEDNESDAY': 'W EH1 N Z D EY0',
    'WEIGH': 'W EY1',
    'WEIGHS': 'W EY1 Z',
    'WEIGHT': 'W EY1 T',
    'WEIGHTS': 'W EY1 T S',
    'WEIRD': 'W IH1 R D',
    'WELCOME': 'W EH1 L K AH0 M',
    'WERE': 'W ER1',
    'WHAT': 'W AH1 T',
    'WHEN': 'W EH1 N',
    'WHERE': 'W EH1 R',
    'WHISTLE': 'W IH1 S AH0 L',
    'WHISTLES': 'W IH1 S AH0 L Z',
    'WHISTLING': 'W IH1 S L IH0 NG',
    'WHO': 'HH UW1',
    'WHOLE': 'HH OW1 L',
    'WHOM': 'HH UW1 M',
    'WHOSE': 'HH UW1 Z',
    'WHY': 'W AY1',
    'WILDLIFE': 'W AY1 L D L AY2 F',
    'WINDOWS': 'W IH1 N D OW0 Z',
    'WITH': 'W IH1 DH',
    'WOLF': 'W UH1 L F',
    'WOLVES': 'W UH1 L V Z',
    'WOMAN': 'W UH1 M AH0 N',
    'WOMB': 'W UW1 M',
    'WOMEN': 'W IH1 M AH0 N',
    'WORLD': 'W ER1 L D',
    'WORRIED': 'W ER1 IY0 D',
    'WORRY': 'W ER1 IY0',
    'WOULD': 'W UH1 D',
    'WRAP': 'R AE1 P',
    'WRATH': 'R AE1 TH',
    'WRECK': 'R EH1 K',
    'WRESTLE': 'R EH1 S AH0 L',
    'WRINKLE': 'R IH1 NG K AH0 L',
    'WRIST': 'R IH1 S T',
    'WRITE': 'R AY1 T',
    'WRITER': 'R AY1 T ER0',
    'WRITES': 'R AY1 T S',
    'WRITTEN': 'R IH1 T AH0 N',
    'WRONG': 'R AO1 NG',
    'WROTE': 'R OW1 T',
    'YACHT': 'Y AA1 T',
    'YACHTS': 'Y AA1 T S',
    'YAY': 'Y EY1',
    'YES': 'Y EH1 S',
    'YO': 'Y OW1',
    'YOLK': 'Y OW1 K',
    'YOU': 'Y UW1',
    'YOUR': 'Y AO1 R',
    'ZUCCHINI': 'Z UW0 K IY1 N IY0',
}

# Unstressed English function words (softened in Real Speech mode).
FUNCTION_WORDS = frozenset({
    "THE", "A", "AN", "TO", "OF", "IN", "ON", "FOR", "WITH", "AS", "AT", "BY",
    "FROM", "THAT", "THIS", "IS", "WAS", "ARE", "WERE", "BE", "BEEN", "AM",
    "AND", "OR", "BUT", "IF", "SO", "IT", "ITS", "HIS", "HER", "OUR", "YOUR",
    "THEIR", "MY", "ME", "HIM", "US", "THEM", "WE", "YOU", "HE", "SHE",
    "THEY", "CAN", "WILL", "JUST", "THAN", "THEN",
})

UNVOICED_CONSONANTS = frozenset({"P", "T", "K", "F", "TH", "S", "SH", "CH", "HH"})
SIBILANT_CONSONANTS = frozenset({"S", "Z", "SH", "ZH", "CH", "JH"})


def strip_stress_code(token: str) -> tuple[str, int]:
    """``"AY1"`` -> ``("AY", 1)``; consonants default to stress 0."""
    base = re.sub(r"[012]$", "", token)
    match = re.search(r"([012])$", token)
    if match:
        stress = int(match.group(1))
    else:
        stress = 1 if PHONEMES.get(base, {}).get("isVowel") else 0
    return base, stress


def get_lexicon_entry_with_stress(word_upper: str):
    """Raw dictionary pronunciation as ``[(code, stress), ...]`` or ``None``."""
    raw = LEXICON.get(word_upper)
    if not raw:
        return None
    return [strip_stress_code(tok) for tok in raw.split()]


def lookup_word_with_morphology(word_upper: str):
    """Dictionary lookup plus plural / past / gerund / adverb stemming."""
    direct = get_lexicon_entry_with_stress(word_upper)
    if direct:
        return direct

    # 1. -IES -> -Y (SYMPHONIES -> SYMPHONY)
    if len(word_upper) > 4 and word_upper.endswith("IES"):
        stem = get_lexicon_entry_with_stress(word_upper[:-3] + "Y")
        if stem:
            return stem + [("Z", 0)]

    # 2. -VES -> -F / -FE (WOLVES -> WOLF)
    if len(word_upper) > 4 and word_upper.endswith("VES"):
        stem_f = (get_lexicon_entry_with_stress(word_upper[:-3] + "F")
                  or get_lexicon_entry_with_stress(word_upper[:-3] + "FE"))
        if stem_f:
            return stem_f[:-1] + [("V", 0), ("Z", 0)]

    # 3. -ES / -S plural & third-person singular
    if (len(word_upper) > 3 and word_upper.endswith("S")
            and not word_upper.endswith("SS")
            and not word_upper.endswith("US")
            and not word_upper.endswith("IS")):
        stem_es = (get_lexicon_entry_with_stress(word_upper[:-2])
                   if word_upper.endswith("ES") else None)
        stem_s = get_lexicon_entry_with_stress(word_upper[:-1])
        base = stem_s or stem_es
        if base:
            last = base[-1][0]
            if last in SIBILANT_CONSONANTS:
                return base + [("IH", 0), ("Z", 0)]
            if last in UNVOICED_CONSONANTS:
                return base + [("S", 0)]
            return base + [("Z", 0)]

    # 4. -IED -> -Y (WORRIED -> WORRY)
    if len(word_upper) > 4 and word_upper.endswith("IED"):
        stem = get_lexicon_entry_with_stress(word_upper[:-3] + "Y")
        if stem:
            return stem + [("D", 0)]

    # 5. -ED past tense
    if len(word_upper) > 4 and word_upper.endswith("ED"):
        base = (get_lexicon_entry_with_stress(word_upper[:-1])
                or get_lexicon_entry_with_stress(word_upper[:-2]))
        if not base and len(word_upper) > 5 and word_upper[-3] == word_upper[-4]:
            base = get_lexicon_entry_with_stress(word_upper[:-3])
        if base:
            last = base[-1][0]
            if last in ("T", "D"):
                return base + [("IH", 0), ("D", 0)]
            if last in UNVOICED_CONSONANTS:
                return base + [("T", 0)]
            return base + [("D", 0)]

    # 6. -ING participle
    if len(word_upper) > 5 and word_upper.endswith("ING"):
        base = (get_lexicon_entry_with_stress(word_upper[:-3])
                or get_lexicon_entry_with_stress(word_upper[:-3] + "E"))
        if not base and len(word_upper) > 6 and word_upper[-4] == word_upper[-5]:
            base = get_lexicon_entry_with_stress(word_upper[:-4])
        if base:
            return base + [("IH", 0), ("NG", 0)]

    # 7. -LY adverb
    if len(word_upper) > 4 and word_upper.endswith("LY"):
        base = get_lexicon_entry_with_stress(word_upper[:-2])
        if base:
            return base + [("L", 0), ("IY", 0)]

    # 8. -ER comparative / agent
    if len(word_upper) > 4 and word_upper.endswith("ER"):
        base = (get_lexicon_entry_with_stress(word_upper[:-2])
                or get_lexicon_entry_with_stress(word_upper[:-1]))
        if base:
            return base + [("ER", 0)]

    # 9. -NESS abstract noun
    if len(word_upper) > 5 and word_upper.endswith("NESS"):
        base = get_lexicon_entry_with_stress(word_upper[:-4])
        if base:
            return base + [("N", 0), ("AH", 0), ("S", 0)]

    return None


def is_vowel_letter(ch: str) -> bool:
    return ch in "AEIOUY"


def analyze_and_normalize_stretch(upper_word: str) -> tuple[str, int]:
    """Collapse ``Hiiii`` / ``goooo`` / ``yaaaay`` to their dictionary root.

    Returns ``(normalized_word, extra_stretch_chars)`` exactly like the HTML
    studio, so a stretched word gets one sustained vowel instead of five
    separate chirps.
    """
    if not upper_word or len(upper_word) <= 2:
        return upper_word, 0
    if upper_word in LEXICON:
        return upper_word, 0

    extra = 0
    collapsed_one = ""
    collapsed_two = ""
    i = 0
    while i < len(upper_word):
        ch = upper_word[i]
        run_len = 1
        while i + run_len < len(upper_word) and upper_word[i + run_len] == ch:
            run_len += 1
        if run_len >= 3:
            extra += run_len - 1
            collapsed_one += ch
            collapsed_two += ch + ch
        elif run_len == 2 and is_vowel_letter(ch) and i + run_len == len(upper_word):
            test_single = upper_word[:-1]
            if test_single in LEXICON:
                extra += 1
                collapsed_one += ch
                collapsed_two += ch
            else:
                collapsed_one += ch + ch
                collapsed_two += ch + ch
        else:
            collapsed_one += ch * run_len
            collapsed_two += ch * run_len
        i += run_len

    if extra > 0:
        if collapsed_one in LEXICON:
            return collapsed_one, extra
        if collapsed_two in LEXICON:
            return collapsed_two, max(1, extra - 1)
        return collapsed_one, extra
    return upper_word, 0


def compute_lexical_seed(word_str: str, phonemes: Iterable[str]) -> int:
    """Deterministic 32-bit fingerprint so each word gets its own contour."""
    value = 0
    payload = (word_str or "") + ":" + "-".join(phonemes or ())
    for ch in payload:
        value = ((value << 5) - value + ord(ch)) & 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return abs(value)


def compile_word_to_phonemes_with_stress(raw_word: str):
    """Grapheme-to-phoneme compiler with Oxford dictionary + English rules."""
    raw_upper = re.sub(r"[^A-Z]", "", (raw_word or "").upper())
    if not raw_upper:
        return []

    direct = lookup_word_with_morphology(raw_upper)
    if direct:
        return direct

    normalized, _extra = analyze_and_normalize_stretch(raw_upper)
    morph = lookup_word_with_morphology(normalized)
    if morph:
        return morph

    if normalized == "I":
        return [("AY", 1)]
    if normalized == "A":
        return [("AH", 0)]

    clean = normalized
    # Terminal silent -MB / -MN (climb, comb, hymn, column, autumn).
    clean = re.sub(r"MB$", "M", clean)
    clean = re.sub(r"MN$", "M", clean)
    # Silent -STLE / -STEN (castle, whistle, listen, fasten).
    clean = re.sub(r"STLE$", "SEL", clean)
    clean = re.sub(r"STEN$", "SEN", clean)
    # Initial silent KN-, GN-, WR-, PS-, PN-, PT-.
    clean = re.sub(r"^(KN|GN)", "N", clean)
    clean = re.sub(r"^WR", "R", clean)
    clean = re.sub(r"^PS", "S", clean)
    clean = re.sub(r"^PN", "N", clean)
    clean = re.sub(r"^PT", "T", clean)

    out: list[tuple[str, int]] = []
    length = len(clean)
    if length == 0:
        return [("AH", 0)]

    has_silent_e = False
    if (length >= 4 and clean[-1] == "E"
            and not is_vowel_letter(clean[-2])
            and is_vowel_letter(clean[-3])):
        tail3 = clean[-3:]
        if tail3 not in ("THE", "NGE"):
            has_silent_e = True

    parse_limit = length - 1 if has_silent_e else length
    i = 0
    vowel_seen = 0

    def push_ph(code: str, stress=None):
        nonlocal vowel_seen
        is_vowel = bool(PHONEMES.get(code, {}).get("isVowel"))
        if stress is None:
            stress = 1 if (is_vowel and vowel_seen == 0) else 0
        if is_vowel:
            vowel_seen += 1
        out.append((code, int(stress)))

    while i < parse_limit:
        rem = clean[i:]
        ch = clean[i]
        nxt = clean[i + 1] if i + 1 < parse_limit else ""
        pair = ch + nxt

        if rem.startswith("TION") or rem.startswith("SION"):
            push_ph("SH", 0); push_ph("AH", 0); push_ph("N", 0); i += 4; continue
        if rem.startswith("CIAN"):
            push_ph("SH", 0); push_ph("AH", 0); push_ph("N", 0); i += 4; continue
        if rem.startswith("CIOUS") or rem.startswith("TIOUS"):
            push_ph("SH", 0); push_ph("AH", 0); push_ph("S", 0); i += 5; continue
        if rem.startswith("SURE"):
            push_ph("ZH", 0); push_ph("ER", 0); i += 4; continue
        if rem.startswith("TURE"):
            push_ph("CH", 0); push_ph("ER", 0); i += 4; continue
        if rem.startswith("OUGH"):
            push_ph("OW", 1); i += 4; continue
        if rem.startswith("AUGH"):
            push_ph("AO", 1); i += 4; continue
        if rem.startswith("EIGH"):
            push_ph("EY", 1); i += 4; continue
        if rem.startswith("IGH"):
            push_ph("AY", 1); i += 3; continue
        if rem.startswith("ING") and i + 3 == length:
            push_ph("IH", 0); push_ph("NG", 0); i += 3; continue
        if rem.startswith("TCH"):
            push_ph("CH", 0); i += 3; continue
        if rem.startswith("DGE"):
            push_ph("JH", 0); i += 3; continue
        if rem.startswith("QUE") and i + 3 == length:
            push_ph("K", 0); i += 3; continue
        if rem.startswith("GUE") and i + 3 == length:
            push_ph("G", 0); i += 3; continue

        if pair == "TH":
            prev_vowel = i > 0 and is_vowel_letter(clean[i - 1])
            next_vowel = i + 2 < length and is_vowel_letter(clean[i + 2])
            push_ph("DH" if (prev_vowel and next_vowel) else "TH", 0)
            i += 2; continue
        if pair == "SH": push_ph("SH", 0); i += 2; continue
        if pair == "CH": push_ph("CH", 0); i += 2; continue
        if pair == "PH": push_ph("F", 0); i += 2; continue
        if pair == "WH": push_ph("W", 0); i += 2; continue
        if pair == "NG": push_ph("NG", 0); i += 2; continue
        if pair == "QU": push_ph("K", 0); push_ph("W", 0); i += 2; continue
        if pair == "CK": push_ph("K", 0); i += 2; continue
        if pair == "GH":
            if i == 0:
                push_ph("G", 0)
            i += 2; continue

        if pair in ("OO", "EW", "UE", "UI"): push_ph("UW"); i += 2; continue
        if pair in ("EE", "EA", "IE"): push_ph("IY"); i += 2; continue
        if pair in ("AI", "AY", "EI"): push_ph("EY"); i += 2; continue
        if pair in ("OA", "OE"): push_ph("OW"); i += 2; continue
        if pair in ("OU", "OW"): push_ph("AW"); i += 2; continue
        if pair in ("OI", "OY"): push_ph("OY"); i += 2; continue
        if pair in ("AU", "AW"): push_ph("AO"); i += 2; continue
        if pair in ("ER", "IR", "UR"): push_ph("ER"); i += 2; continue
        if pair == "AR": push_ph("AA"); push_ph("R", 0); i += 2; continue
        if pair == "OR": push_ph("AO"); push_ph("R", 0); i += 2; continue

        if ch == nxt and not is_vowel_letter(ch):
            i += 1
            continue

        silent_e_target = has_silent_e and (i == length - 3)
        if ch == "A": push_ph("EY" if silent_e_target else "AE"); i += 1; continue
        if ch == "E": push_ph("IY" if (silent_e_target or i == length - 1) else "EH"); i += 1; continue
        if ch == "I": push_ph("AY" if (silent_e_target or (i == length - 1 and length <= 2)) else "IH"); i += 1; continue
        if ch == "O": push_ph("OW" if (silent_e_target or i == length - 1) else "AA"); i += 1; continue
        if ch == "U": push_ph("UW" if silent_e_target else "AH"); i += 1; continue
        if ch == "Y":
            if i == 0 and length > 1:
                push_ph("Y", 0)
            elif silent_e_target or (i == length - 1 and length <= 3):
                push_ph("AY", 1)
            elif (i > 0 and i < length - 1
                  and not is_vowel_letter(clean[i - 1])
                  and not is_vowel_letter(nxt)):
                push_ph("IH", 1)
            else:
                push_ph("IY", 0)
            i += 1; continue

        if ch == "C": push_ph("S" if nxt in "EIY" else "K", 0); i += 1; continue
        if ch == "G": push_ph("JH" if nxt in "EIY" else "G", 0); i += 1; continue
        if ch == "J": push_ph("JH", 0); i += 1; continue
        if ch == "H": push_ph("HH", 0); i += 1; continue
        if ch == "X": push_ph("K", 0); push_ph("S", 0); i += 1; continue
        if ch in PHONEMES:
            push_ph(ch, 0)
        i += 1

    return out if out else [("AH", 0)]


def compile_word_to_phonemes(raw_word: str):
    return [code for code, _stress in compile_word_to_phonemes_with_stress(raw_word)]


def parse_sentence_to_words(text: str):
    """Tokenise text into word objects carrying phonemes, stress and prosody.

    Mirrors ``parseSentenceToWords`` in the HTML studio, including the
    stretched-word multiplier, function-word softening and the final
    question / exclamation flags.
    """
    trimmed = (text or "").strip()
    if not trimmed:
        return []
    raw_tokens = re.split(r"\s+", trimmed)
    words = []
    sentence_question = bool(re.search(r"\?\s*$", trimmed))
    sentence_exclaim = bool(re.search(r"!\s*$", trimmed))

    for raw in raw_tokens:
        clean = re.sub(r"[^a-zA-Z]", "", raw)
        if not clean:
            continue
        has_comma = any(ch in raw for ch in ",;:")
        has_period = "." in raw
        token_question = "?" in raw
        token_exclaim = "!" in raw
        stretch_word, extra_stretch = analyze_and_normalize_stretch(clean.upper())
        ph_objs = compile_word_to_phonemes_with_stress(clean)
        phonemes = [code for code, _s in ph_objs]
        stresses = [stress for _c, stress in ph_objs]
        if not phonemes:
            continue

        stretch_mult = (min(3.4, 1.0 + extra_stretch * 0.48)
                        if extra_stretch > 0 else 1.0)
        is_function = (stretch_word in FUNCTION_WORDS
                       and not token_exclaim and not token_question)
        words.append({
            "wordIdx": len(words),
            "display": raw,
            "cleanUpper": stretch_word,
            "phonemes": phonemes,
            "stresses": stresses,
            "isFunctionWord": is_function,
            "stretchMult": stretch_mult,
            "isStretched": extra_stretch > 0,
            "lexicalSeed": compute_lexical_seed(stretch_word, phonemes),
            "hasComma": has_comma,
            "hasPeriod": has_period,
            "pauseAfter": (0.18 if (has_period or token_question or token_exclaim)
                           else (0.12 if has_comma else 0.032)),
            "isQuestion": token_question,
            "isExclaim": token_exclaim,
        })

    if words:
        if sentence_question:
            words[-1]["isQuestion"] = True
        if sentence_exclaim:
            words[-1]["isExclaim"] = True
    return words
