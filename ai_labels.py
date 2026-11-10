# -*- coding: utf-8 -*-
"""模型标签体系：PlantVillage 38 个细粒度类别 -> 中文名 / 作物 / 平台知识库映射。

模型输出的类别是国际通用的 PlantVillage 体系，这里负责把它翻译成中文，
并尽可能挂接到平台已有的作物科普与病虫害防治知识库条目上。
"""

# 细粒度类别中文名
LABEL_CN = {
    "Apple___Apple_scab": "苹果黑星病",
    "Apple___Black_rot": "苹果黑腐病",
    "Apple___Cedar_apple_rust": "苹果锈病",
    "Apple___healthy": "苹果（健康）",
    "Blueberry___healthy": "蓝莓（健康）",
    "Cherry___Powdery_mildew": "樱桃白粉病",
    "Cherry___healthy": "樱桃（健康）",
    "Corn___Cercospora_leaf_spot Gray_leaf_spot": "玉米灰斑病",
    "Corn___Common_rust_": "玉米普通锈病",
    "Corn___Northern_Leaf_Blight": "玉米大斑病",
    "Corn___healthy": "玉米（健康）",
    "Grape___Black_rot": "葡萄黑腐病",
    "Grape___Esca_(Black_Measles)": "葡萄蔓枯病（Esca）",
    "Grape___Leaf_blight_(Isariopsis_Leaf_Spot)": "葡萄叶枯病",
    "Grape___healthy": "葡萄（健康）",
    "Orange___Haunglongbing_(Citrus_greening)": "柑橘黄龙病",
    "Peach___Bacterial_spot": "桃细菌性穿孔病",
    "Peach___healthy": "桃（健康）",
    "Pepper,_bell___Bacterial_spot": "辣椒细菌性叶斑病",
    "Pepper,_bell___healthy": "辣椒（健康）",
    "Potato___Early_blight": "马铃薯早疫病",
    "Potato___Late_blight": "马铃薯晚疫病",
    "Potato___healthy": "马铃薯（健康）",
    "Raspberry___healthy": "树莓（健康）",
    "Soybean___healthy": "大豆（健康）",
    "Squash___Powdery_mildew": "南瓜白粉病",
    "Strawberry___Leaf_scorch": "草莓叶焦病",
    "Strawberry___healthy": "草莓（健康）",
    "Tomato___Bacterial_spot": "番茄细菌性斑点病",
    "Tomato___Early_blight": "番茄早疫病",
    "Tomato___Late_blight": "番茄晚疫病",
    "Tomato___Leaf_Mold": "番茄叶霉病",
    "Tomato___Septoria_leaf_spot": "番茄斑枯病",
    "Tomato___Spider_mites Two-spotted_spider_mite": "番茄二斑叶螨危害",
    "Tomato___Target_Spot": "番茄靶斑病",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus": "番茄黄化曲叶病毒病",
    "Tomato___Tomato_mosaic_virus": "番茄花叶病毒病",
    "Tomato___healthy": "番茄（健康）",
}

# 作物（模型标签前缀 -> 中文 / 平台 slug）
CROP_CN = {
    "Apple": "苹果", "Blueberry": "蓝莓", "Cherry": "樱桃", "Corn": "玉米",
    "Grape": "葡萄", "Orange": "柑橘", "Peach": "桃", "Pepper,_bell": "辣椒",
    "Potato": "马铃薯", "Raspberry": "树莓", "Soybean": "大豆", "Squash": "南瓜",
    "Strawberry": "草莓", "Tomato": "番茄",
}

# 模型作物 -> 平台作物 slug（平台未收录的作物为空）
CROP_TO_SLUG = {
    "Apple": "apple", "Corn": "maize", "Grape": "grape", "Tomato": "tomato",
    "Potato": "potato", "Pepper,_bell": "pepper", "Strawberry": "strawberry",
    "Orange": "citrus", "Soybean": "soybean",
}

# 模型细粒度类别 -> 平台病虫害 slug（语义完全一致才映射，避免张冠李戴）
LABEL_TO_DISEASE_SLUG = {
    # 平台知识库原本收录的病害
    "Corn___Northern_Leaf_Blight": "maize-northern-blight",
    "Tomato___Early_blight": "tomato-early-blight",
    "Tomato___Late_blight": "tomato-late-blight",
    "Potato___Late_blight": "potato-late-blight",
    # 为配合模型能力同步扩充的病害条目
    "Apple___Apple_scab": "apple-scab",
    "Apple___Black_rot": "apple-black-rot",
    "Apple___Cedar_apple_rust": "apple-rust",
    "Corn___Cercospora_leaf_spot Gray_leaf_spot": "maize-gray-leaf-spot",
    "Corn___Common_rust_": "maize-common-rust",
    "Grape___Black_rot": "grape-black-rot",
    "Grape___Esca_(Black_Measles)": "grape-esca",
    "Grape___Leaf_blight_(Isariopsis_Leaf_Spot)": "grape-leaf-blight",
    "Potato___Early_blight": "potato-early-blight",
    "Tomato___Bacterial_spot": "tomato-bacterial-spot",
    "Tomato___Leaf_Mold": "tomato-leaf-mold",
    "Tomato___Septoria_leaf_spot": "tomato-septoria-leaf-spot",
    "Tomato___Target_Spot": "tomato-target-spot",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus": "tomato-yellow-leaf-curl",
    "Tomato___Tomato_mosaic_virus": "tomato-mosaic-virus",
    "Orange___Haunglongbing_(Citrus_greening)": "citrus-huanglongbing",
    "Pepper,_bell___Bacterial_spot": "pepper-bacterial-spot",
    "Strawberry___Leaf_scorch": "strawberry-leaf-scorch",
}


def crop_of(label: str) -> str:
    return label.split("___")[0]


def cn(label: str) -> str:
    return LABEL_CN.get(label, label)


def crop_cn(label: str) -> str:
    return CROP_CN.get(crop_of(label), crop_of(label))


def is_healthy(label: str) -> bool:
    return label.endswith("___healthy")
