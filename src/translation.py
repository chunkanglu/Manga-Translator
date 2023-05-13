import cv2
import numpy as np
import largestinteriorrectangle as lir
import os
import re
from pathlib import Path
from requests import get
from tqdm import tqdm

from detectron2 import model_zoo
from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor

from deep_translator import GoogleTranslator, DeeplTranslator
from manga_ocr import MangaOcr
from PIL import Image, ImageFont, ImageDraw


def download_model(seg_model_path):
    model_url = "https://github.com/chunkanglu/Manga-Translator/releases/download/v0.1.0/model.pth"

    res = get(model_url, stream=True)
    file_size = int(res.headers.get("Content-Length", 0))
    block_size = 1024
    progress_bar = tqdm(total=file_size, unit="iB", unit_scale=True)

    with open(seg_model_path, "wb") as f:
        for data in res.iter_content(block_size):
            progress_bar.update(len(data))
            f.write(data)

    progress_bar.close()


def download_font(font):
    font_url = "https://github.com/chunkanglu/Manga-Translator/releases/download/v0.1.0/wildwordsroman.TTF"

    res = get(font_url, stream=True)
    file_size = int(res.headers.get("Content-Length", 0))
    block_size = 1024
    progress_bar = tqdm(total=file_size, unit="iB", unit_scale=True)

    with open(font, "wb") as f:
        for data in res.iter_content(block_size):
            progress_bar.update(len(data))
            f.write(data)


class Translation:
    def __init__(self,
                 src="ja",
                 tgt="en",
                 seg_model_path="assets\model.pth",
                 text_buffer=0.9,
                 font="assets\wildwordsroman.TTF",
                 api_key=None) -> None:

        model_path = Path(seg_model_path)
        font_path = Path(font)

        if not model_path.exists():
            download_model(seg_model_path)

        if not font_path.exists():
            download_font(font)

        if (src == "ja"):
            self.ocr = MangaOcr()
        # self.tr = DeeplTranslator(api_key=api_key, source=src, target=tgt)
        self.tr = GoogleTranslator(source=src, target=tgt)

        seg_model_head, seg_model_tail = os.path.split(seg_model_path)
        cfg_pred = get_cfg()
        # cfg_pred.MODEL.DEVICE = "cpu"
        cfg_pred.OUTPUT_DIR = seg_model_head
        cfg_pred.merge_from_file(model_zoo.get_config_file(
            "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"))
        cfg_pred.MODEL.WEIGHTS = os.path.join(
            cfg_pred.OUTPUT_DIR, seg_model_tail)
        cfg_pred.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.9

        self.predictor = DefaultPredictor(cfg_pred)

        self.text_buffer = text_buffer
        self.font = font

    def read_img(self, img_path):
        img_t = Image.open(img_path)
        img = np.array(img_t)

        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        return img.copy()

    def predict(self, img):
        return self.predictor(img)["instances"].to("cpu").get_fields()

    # def clean_text_boxes(self, img, prediction):
    #     img_copy = img.copy()
    #     for mask in prediction["pred_masks"].numpy():
    #         img_copy[mask, :] = [255, 255, 255]
    #     return img_copy

    # def get_cropped_bboxs(self, img, prediction):
    #     bboxs = prediction["pred_boxes"].tensor.numpy().astype(int)

    #     cropped = []
    #     for b in bboxs:
    #         x1, y1, x2, y2 = b
    #         crop = img[y1:y2, x1:x2]
    #         cropped.append(crop)

    #     return cropped

    def get_largest_text_box(self, mask):
        return lir.lir(mask.numpy().astype(bool))

    # def get_text_array(self, bboxs):
    #     text = []
    #     for i in bboxs:
    #         text.append(self.ocr(Image.fromarray(i)))
    #     return text

    # def get_translated_text(self, text_array):
    #     tr_text = []
    #     for i in text_array:
    #         tr_text.append(self.tr.translate(i))
    #     print(text_array)
    #     print(tr_text)
    #     return tr_text
    
    def clean_text_box(self, img, mask):
        img_copy = img.copy()
        img_copy[mask, :] = [255, 255, 255]
        return img_copy
    
    def get_crop(self, img, bbox):
        x1, y1, x2, y2 = bbox
        return img[y1:y2, x1:x2]
    
    def get_text(self, img):
        return self.ocr(Image.fromarray(img))
    
    def get_tr_text(self, text):
        return self.tr.translate(text)

    def draw_text(self, mask, tr_text, img_to_draw):
        (x, y, w, h) = self.get_largest_text_box(mask)
        mid_v = x + w // 2
        mid_h = y + h // 2
        maxBuffer = int(w * self.text_buffer)
        font_size = 200

        if tr_text is None:
            return

        text_arr = re.split(r'[\s\-]', tr_text)
        multi_line = "\n"
        next_line = ""

        while True:

            multi_line = "\n"
            next_line = ""

            for t in text_arr:

                while (img_to_draw.textlength(t,
                                              font=ImageFont.truetype(self.font, font_size)) >= maxBuffer):
                    font_size -= 2

                if (img_to_draw.textlength(next_line + " " + t,
                                           font=ImageFont.truetype(self.font, font_size)) < maxBuffer):
                    if (next_line == ""):
                        next_line = t
                    else:
                        next_line = next_line + " " + t

                elif (img_to_draw.textlength(next_line,
                                             font=ImageFont.truetype(self.font, font_size)) < maxBuffer):
                    multi_line += next_line + "\n"
                    next_line = t

            multi_line += next_line + "\n"

            left, top, right, bottom = img_to_draw.multiline_textbbox((mid_v, mid_h),
                                                                      multi_line,
                                                                      font=ImageFont.truetype(self.font, font_size))

            if (bottom-top < h):
                break

            font_size -= 2

        img_to_draw.multiline_text((mid_v, mid_h),
                                   multi_line,
                                   (0, 0, 0),
                                   font=ImageFont.truetype(
                                       self.font, font_size),
                                   anchor="mm",
                                   align="center")

    def translate(self, img_path):
        img = self.read_img(img_path)
        output_img = None
        preds = self.predict(img)

        masks = preds["pred_masks"].numpy()
        bboxs = preds["pred_boxes"].tensor.numpy().astype(int)

        for mask, bbox in zip(masks, bboxs):
            img = self.clean_text_box(img, mask)
            output_img = Image.fromarray(img)
            draw = ImageDraw.Draw(output_img)

            crop = self.get_crop(img, bbox)
            og_text = self.get_text(crop)
            tr_text = self.get_tr_text(og_text)

            self.draw_text(mask, tr_text, draw)

        return output_img





        clean_img = self.clean_text_boxes(img, preds)
        bboxs = self.get_cropped_bboxs(img, preds)

        og_text = self.get_text_array(bboxs)
        translated_text = self.get_translated_text(og_text)

        output_img = Image.fromarray(clean_img)
        draw = ImageDraw.Draw(output_img)

        for mask, tr_text in zip(preds["pred_masks"], translated_text):
            self.draw_text(mask, tr_text, draw)

        return output_img
