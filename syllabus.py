"""Subject registry: syllabus-style guidance and topic lists (edit freely)."""

TYPE_LABELS = {
    "mcq": "Multiple choice",
    "short": "Short answer",
    "structured": "Structured / open-ended",
}
TYPE_ORDER = ["mcq", "short", "structured"]  # paper order: Booklet A style first

SUBJECTS = {
    "PSLE Math": {
        "style": """Singapore PSLE Mathematics. Use SGD, local names (Ahmad, Mei Ling, Priya, Wei Jie)
and HDB/hawker/MRT contexts. Paper 1 style is short (1-2 marks); Paper 2 style is multi-step word
problems (3-5 marks). Worked solutions use the bar-model approach where it fits, one step per line.""",
        "topics": ["Whole numbers", "Fractions", "Decimals", "Percentage", "Ratio", "Average",
                   "Speed and rate", "Algebra", "Area and perimeter", "Volume", "Angles",
                   "Circles", "Pie charts and graphs"],
        "default_types": ["short", "structured"],
    },
    "PSLE Science": {
        "style": """Singapore PSLE Science. Use the exact terms the syllabus expects (evaporation,
condensation, photosynthesis, adaptation). MCQs test one concept with plausible distractors; open-ended
questions are 2-3 marks and the answer uses keywords an examiner looks for.""",
        "topics": ["Plant parts and functions", "Human digestive system",
                   "Respiratory and circulatory systems", "Life cycles", "Adaptations",
                   "Matter and states", "Water cycle", "Heat energy", "Light energy", "Forces",
                   "Electricity and circuits", "Magnets", "Food webs and environment"],
        "default_types": ["mcq", "structured"],
    },
    "PSLE English": {
        "style": """Singapore PSLE English Language. Self-contained items only: never refer to a reading
passage or picture. Use natural Singapore school contexts. Grammar and vocabulary MCQs have one clearly
correct option. Synthesis and transformation questions give two sentences or a sentence plus a starting
phrase and require one combined or rewritten sentence; mark_scheme awards marks for the correct structure
and for grammatical accuracy.""",
        "topics": ["Grammar (tenses and subject-verb agreement)",
                   "Grammar (prepositions and articles)",
                   "Vocabulary (word meaning)", "Vocabulary (phrasal verbs and idioms)",
                   "Synthesis (connectors and conditionals)",
                   "Transformation (active/passive and reported speech)",
                   "Editing for spelling and grammar"],
        "default_types": ["mcq", "structured"],
    },
    "Sec E-Math (O-Level)": {
        "style": """Singapore GCE O-Level Elementary Mathematics. Use exam command words (Solve, Express,
Find, Show that). Marks in line with the working required. Worked solutions show method lines,
with units and 3 significant figures or 1 decimal place where appropriate.""",
        "topics": ["Quadratic equations and functions", "Simultaneous equations",
                   "Indices and standard form", "Algebraic manipulation and formulae",
                   "Inequalities", "Coordinate geometry", "Trigonometry", "Mensuration",
                   "Similarity", "Circle properties", "Vectors", "Probability", "Statistics"],
        "default_types": ["short", "structured"],
    },
    "Sec A-Math (O-Level)": {
        "style": """Singapore GCE O-Level Additional Mathematics. Exam command words (Solve, Show that,
Prove, Find the exact value). Work is algebra-heavy; give exact answers (surds, ln, pi) where natural.
Worked solutions show each method line.""",
        "topics": ["Quadratic functions", "Equations and inequalities", "Surds",
                   "Polynomials and partial fractions", "Binomial theorem",
                   "Exponential and logarithmic functions", "Coordinate geometry",
                   "Linear law", "Trigonometry", "Differentiation", "Integration", "Kinematics"],
        "default_types": ["short", "structured"],
    },
    "O-Level Physics": {
        "style": """Singapore GCE O-Level Physics. Use SI units and state them in answers. Calculation
questions give the formula in the worked solution. Explain-type questions have mark_scheme points using
examiner keywords.""",
        "topics": ["Kinematics", "Dynamics", "Mass, weight and density", "Turning effects of forces",
                   "Pressure", "Energy, work and power", "Thermal physics", "Waves", "Light", "Sound",
                   "Electricity and D.C. circuits", "Practical electricity", "Magnetism",
                   "Electromagnetism"],
        "default_types": ["mcq", "structured"],
    },
    "O-Level Chemistry": {
        "style": """Singapore GCE O-Level Chemistry. Use correct chemical formulae and state symbols where
relevant. Calculation questions use Ar values given in the question. Explain-type questions have
mark_scheme points using examiner keywords.""",
        "topics": ["Atomic structure", "Chemical bonding", "Stoichiometry and the mole concept",
                   "Acids, bases and salts", "Redox", "Periodic table", "Metals",
                   "Organic chemistry", "Rate of reaction", "Energy changes", "Electrochemistry"],
        "default_types": ["mcq", "structured"],
    },
    "O-Level Biology": {
        "style": """Singapore GCE O-Level Biology. Use syllabus terms precisely. Explain-type questions
have mark_scheme points using examiner keywords. Do not refer to diagrams you cannot show.""",
        "topics": ["Cell structure and organisation", "Movement of substances", "Enzymes",
                   "Nutrition", "Transport in humans and plants", "Respiration", "Reproduction",
                   "Inheritance", "Ecology and human impact"],
        "default_types": ["mcq", "structured"],
    },
}
