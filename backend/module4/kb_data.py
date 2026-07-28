"""
kb_data.py

Static medical knowledge base content for Module 4's RAG system.

Scope decision: focused on the common chest X-ray finding set (the same
condition family most chest-radiograph FYP vision pipelines, e.g. CheXpert /
NIH ChestX-ray14 style label sets, are trained to detect). This keeps the KB
tightly scoped instead of a general medical encyclopedia, matching Module 6's
approach of a small, focused, verifiable KB rather than a huge scraped one.

Each entry is written for a PATIENT audience (plain language), since the
generation prompt uses these only as supporting/definitional context to
explain terms already present in the patient's own report -- not as a
standalone answer source.

If your vision modules ultimately detect a different / narrower set of
conditions, trim or extend this list to match. Every entry follows the same
schema so kb_indexer.py can chunk them consistently.
"""

KB_ENTRIES = [
    {
        "condition": "Cardiomegaly",
        "definition": "Cardiomegaly means the heart appears larger than normal on an X-ray. It's a finding, not a disease by itself -- it's usually a sign that the heart is working harder than it should, often because of high blood pressure, a valve problem, or a weakened heart muscle.",
        "common_causes": "High blood pressure (hypertension), heart valve disease, cardiomyopathy (weakened heart muscle), long-term heart failure, or fluid buildup around the heart.",
        "typical_symptoms": "Shortness of breath, fatigue, swelling in the legs or ankles, irregular heartbeat. Some people have no symptoms at all and it's only found on imaging.",
        "general_management": "Usually managed with medication (blood pressure control, diuretics), lifestyle changes (reduced salt intake, monitoring weight), and treating the underlying cause. Severity and treatment plan depend entirely on the cause, which is why the same X-ray finding can mean very different things for different patients.",
    },
    {
        "condition": "Pneumonia",
        "definition": "Pneumonia is an infection that inflames the air sacs in one or both lungs, which can fill with fluid or pus. On an X-ray, infected areas often show up as cloudy or white patches (called consolidation).",
        "common_causes": "Bacteria, viruses, or fungi. Bacterial pneumonia is the most common type needing antibiotic treatment.",
        "typical_symptoms": "Cough (often with phlegm), fever, chills, difficulty breathing, chest pain when breathing or coughing, fatigue.",
        "general_management": "Depends on the cause -- bacterial pneumonia is treated with antibiotics, viral pneumonia with supportive care and rest. Severe cases may need hospitalization and oxygen support.",
    },
    {
        "condition": "Pleural Effusion",
        "definition": "A pleural effusion is a buildup of fluid in the space between the lung and the chest wall (the pleural space). On an X-ray it shows up as a blunting or whiting-out of the lower lung edge.",
        "common_causes": "Heart failure, pneumonia, cancer, kidney disease, liver disease, or blood clots in the lung (pulmonary embolism).",
        "typical_symptoms": "Shortness of breath, chest pain (especially with deep breaths), dry cough. Small effusions may cause no symptoms.",
        "general_management": "Treating the underlying cause is the priority. Larger effusions causing breathing difficulty may need to be drained (a procedure called thoracentesis).",
    },
    {
        "condition": "Pneumothorax",
        "definition": "A pneumothorax is a collapsed lung -- air has leaked into the space between the lung and chest wall, putting pressure on the lung so it can't expand fully. On an X-ray this shows as a dark area with no lung markings at the edge of the chest.",
        "common_causes": "Chest injury, a ruptured air blister (bleb) on the lung surface, underlying lung disease (like COPD), or sometimes no clear cause (spontaneous pneumothorax).",
        "typical_symptoms": "Sudden sharp chest pain, shortness of breath, rapid heart rate. Can range from mild to a medical emergency depending on size.",
        "general_management": "Small ones may be monitored and resolve on their own. Larger ones typically need a chest tube to re-expand the lung. This is sometimes treated urgently.",
    },
    {
        "condition": "Atelectasis",
        "definition": "Atelectasis means part of the lung has partially or fully collapsed and isn't filling with air properly, often because a small airway is blocked. On an X-ray it appears as a shrunken, denser patch of lung tissue.",
        "common_causes": "Mucus blocking an airway, shallow breathing after surgery, a tumor pressing on an airway, or prolonged bed rest.",
        "typical_symptoms": "Can be symptomless if mild. Larger areas may cause shortness of breath, cough, or chest discomfort.",
        "general_management": "Often improves with deep breathing exercises, physical therapy, or treating the underlying blockage. Rarely needs invasive treatment.",
    },
    {
        "condition": "Consolidation",
        "definition": "Consolidation refers to lung tissue that has filled with fluid, pus, blood, or other material instead of air, making it appear as a dense white patch on an X-ray. It's most often a sign of infection.",
        "common_causes": "Pneumonia is the most common cause. Less commonly: bleeding in the lung, fluid buildup, or certain cancers.",
        "typical_symptoms": "Cough, fever, difficulty breathing -- symptoms typically mirror whatever is causing the consolidation (most often pneumonia).",
        "general_management": "Depends entirely on the underlying cause; if infectious, antibiotics or antivirals are typical.",
    },
    {
        "condition": "Pulmonary Edema",
        "definition": "Pulmonary edema is fluid buildup in the air sacs of the lungs, which makes breathing difficult. On an X-ray it often shows a hazy, symmetric pattern radiating from the center of the chest.",
        "common_causes": "Most commonly heart failure (fluid backs up into the lungs when the heart can't pump effectively), but also kidney failure, high altitude exposure, or certain lung injuries.",
        "typical_symptoms": "Shortness of breath (especially lying flat), a feeling of drowning or suffocating, wheezing, coughing up frothy or blood-tinged mucus.",
        "general_management": "Diuretics to remove excess fluid, oxygen support, and treatment of the underlying heart or kidney problem. Can be a medical emergency if severe.",
    },
    {
        "condition": "Pulmonary Nodule / Mass",
        "definition": "A nodule is a small round spot on the lung (usually under 3cm); a mass is a larger version of the same thing. Most nodules found incidentally are benign, but size, shape, and growth over time matter for figuring out what it is.",
        "common_causes": "Scar tissue from old infections, benign growths, or -- less commonly, but why doctors take them seriously -- early-stage lung cancer.",
        "typical_symptoms": "Usually no symptoms at all -- most are found incidentally on imaging done for another reason.",
        "general_management": "Often monitored with follow-up scans to check for growth. Depending on size, shape, and risk factors, a biopsy may be recommended to confirm what it is.",
    },
    {
        "condition": "Rib Fracture",
        "definition": "A rib fracture is a break or crack in one of the rib bones, visible on an X-ray as a disruption in the normally smooth bone line.",
        "common_causes": "Trauma (falls, accidents, direct blows to the chest), or in some cases repeated stress/coughing in people with weakened bones.",
        "typical_symptoms": "Sharp localized chest pain that worsens with breathing, coughing, or movement; tenderness over the fracture site.",
        "general_management": "Most rib fractures heal on their own with pain control and breathing exercises (to prevent lung complications like pneumonia). Severe or multiple fractures may need closer monitoring.",
    },
    {
        "condition": "Emphysema",
        "definition": "Emphysema is a chronic lung condition where the air sacs in the lungs are damaged and lose their elasticity, making it hard to exhale fully. On an X-ray, lungs often appear larger/flatter than normal (hyperinflated).",
        "common_causes": "Long-term smoking is the leading cause. Less commonly, a genetic condition (alpha-1 antitrypsin deficiency) or long-term exposure to lung irritants.",
        "typical_symptoms": "Progressive shortness of breath, chronic cough, wheezing, reduced exercise tolerance. It's a form of COPD (chronic obstructive pulmonary disease).",
        "general_management": "Not reversible, but manageable: quitting smoking, inhalers/bronchodilators, pulmonary rehabilitation, and oxygen therapy in advanced cases.",
    },
    {
        "condition": "Hilar Lymphadenopathy",
        "definition": "This means the lymph nodes near the center of the chest, where the airways enter the lungs, appear enlarged on an X-ray. It's a finding that points to something else going on rather than a disease itself.",
        "common_causes": "Infections (including tuberculosis), sarcoidosis (an inflammatory condition), or in some cases cancer (lung cancer or lymphoma).",
        "typical_symptoms": "Often no direct symptoms from the lymph nodes themselves; symptoms usually relate to the underlying cause (cough, fever, weight loss, night sweats).",
        "general_management": "Requires figuring out the underlying cause, often with further imaging (CT scan) or a biopsy, since treatment differs completely between infection, inflammation, and cancer.",
    },
    {
        "condition": "Interstitial Lung Pattern / Fibrosis",
        "definition": "This describes a reticular (net-like) or streaky pattern in the lung tissue on an X-ray, suggesting scarring or thickening of the tissue between the air sacs rather than the air sacs themselves.",
        "common_causes": "Long-term exposure to lung irritants, autoimmune diseases, certain medications, or idiopathic pulmonary fibrosis (a scarring disease with no clear cause).",
        "typical_symptoms": "Gradually worsening shortness of breath, dry cough, fatigue -- symptoms often develop slowly over months to years.",
        "general_management": "Focused on slowing progression (certain medications), pulmonary rehabilitation, and oxygen support as needed. A CT scan is usually needed to characterize the pattern more precisely than an X-ray can.",
    },
]
