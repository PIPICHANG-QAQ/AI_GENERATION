import React, { useRef, useState } from "react";
import { Check, Copy, ImagePlus, Library, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QUESTION_IMAGE_REF_MIME, getImageKey, getQuestionImageLabel, questionImageSrc, type QuestionImage } from "@/lib/question";

const MAX_SIZE = 5 * 1024 * 1024;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

export function QuestionImageUploader({
  images,
  onChange,
  readOnly = false,
  uploadFiles,
  libraryImages = [],
  onSelectLibraryImages,
}: {
  images: QuestionImage[];
  onChange: (images: QuestionImage[]) => void;
  readOnly?: boolean;
  uploadFiles?: (files: File[]) => Promise<QuestionImage[]>;
  libraryImages?: QuestionImage[];
  onSelectLibraryImages?: (images: QuestionImage[]) => Promise<QuestionImage[]> | QuestionImage[];
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [selectedLibraryKeys, setSelectedLibraryKeys] = useState<string[]>([]);
  const [selectingLibrary, setSelectingLibrary] = useState(false);

  const mergeImages = (base: QuestionImage[], appended: QuestionImage[]) => {
    const seen = new Set(base.map(getImageKey).filter(Boolean));
    const merged = [...base];
    appended.forEach((img) => {
      const key = getImageKey(img);
      if (!key || seen.has(key)) return;
      seen.add(key);
      merged.push(img);
    });
    return merged;
  };

  const addFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setError("");
    const files = Array.from(fileList);
    const invalid = files.find((file) => !file.type.startsWith("image/"));
    if (invalid) {
      setError("仅支持上传图片文件");
      return;
    }
    const tooLarge = files.find((file) => file.size > MAX_SIZE);
    if (tooLarge) {
      setError("单张图片需小于 5MB");
      return;
    }
    if (uploadFiles) {
      try {
        onChange(await uploadFiles(files));
      } catch (error) {
        setError(error instanceof Error ? error.message : "图片上传失败，请重试");
      }
      return;
    }
    const accepted: QuestionImage[] = [];
    for (const file of files) {
      try {
        const url = await readAsDataUrl(file);
        accepted.push({ name: file.name, url });
      } catch {
        setError("部分图片读取失败，请重试");
      }
    }
    if (accepted.length === 0) return;
    const existing = new Set(images.map((img) => img.url || img.path || ""));
    const deduped = accepted.filter((img) => {
      const key = img.url || img.path || "";
      if (existing.has(key)) return false;
      existing.add(key);
      return true;
    });
    if (deduped.length > 0) onChange([...images, ...deduped]);
  };

  const toggleLibraryImage = (img: QuestionImage) => {
    const key = getImageKey(img);
    if (!key) return;
    setSelectedLibraryKeys((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  };

  const confirmLibrarySelection = async () => {
    const selected = libraryImages.filter((img) => selectedLibraryKeys.includes(getImageKey(img)));
    if (selected.length === 0) {
      setError("请先选择题图库图片");
      return;
    }
    setError("");
    setSelectingLibrary(true);
    try {
      const next = onSelectLibraryImages
        ? await onSelectLibraryImages(selected)
        : mergeImages(images, selected);
      onChange(next);
      setSelectedLibraryKeys([]);
      setLibraryOpen(false);
    } catch (error) {
      setError(error instanceof Error ? error.message : "关联题图库图片失败，请重试");
    } finally {
      setSelectingLibrary(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (readOnly) return;
    void addFiles(e.dataTransfer.files);
  };

  const removeAt = (index: number) => {
    onChange(images.filter((_, i) => i !== index));
  };

  const srcOf = (img: QuestionImage) => questionImageSrc(img.url || img.path);
  const imageLabel = (img: QuestionImage, index: number) => getQuestionImageLabel(img, index);
  const refToken = (img: QuestionImage, index: number) => `![](${imageLabel(img, index)})`;

  const handleRefDragStart = (img: QuestionImage, index: number) => (e: React.DragEvent) => {
    const token = refToken(img, index);
    e.dataTransfer.setData(QUESTION_IMAGE_REF_MIME, token);
    e.dataTransfer.setData("text/plain", token);
    e.dataTransfer.effectAllowed = "copy";
  };

  const copyRef = async (img: QuestionImage, index: number) => {
    const token = refToken(img, index);
    try {
      await navigator.clipboard.writeText(token);
      setError("");
    } catch {
      setError(`复制失败，请手动输入 ${token}`);
    }
  };

  return (
    <div className="space-y-2">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((img, i) => (
            <div
              key={getImageKey(img) || i}
              className="relative group w-24 h-24 rounded-md border border-border bg-card overflow-hidden flex items-center justify-center"
              title={img.name || imageLabel(img, i)}
              draggable={!readOnly}
              onDragStart={handleRefDragStart(img, i)}
            >
              <span className="absolute left-1 top-1 z-10 rounded bg-background/90 px-1.5 py-0.5 text-[10px] font-medium text-foreground shadow-sm">
                {imageLabel(img, i)}
              </span>
              {srcOf(img) ? (
                <img
                  src={srcOf(img)}
                  alt={img.name || imageLabel(img, i)}
                  className="max-w-full max-h-full object-contain cursor-pointer"
                  onClick={() => window.open(srcOf(img), "_blank")}
                />
              ) : (
                <span className="text-xs text-muted-foreground px-1 text-center">
                  {img.name || "无预览"}
                </span>
              )}
              {!readOnly && (
                <div className="absolute right-1 top-1 z-10 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void copyRef(img, i);
                    }}
                    className="w-5 h-5 inline-flex items-center justify-center rounded-full bg-background/95 text-foreground shadow-sm hover:bg-accent"
                    title={`复制引用 ${refToken(img, i)}`}
                  >
                    <Copy className="w-3 h-3" />
                  </button>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      removeAt(i);
                    }}
                    className="w-5 h-5 inline-flex items-center justify-center rounded-full bg-destructive/90 text-destructive-foreground shadow-sm"
                    title="移除题图"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!readOnly && (
        <div className="space-y-2">
          {libraryImages.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full gap-2"
              onClick={() => {
                setSelectedLibraryKeys([]);
                setLibraryOpen(true);
              }}
            >
              <Library className="w-4 h-4" />
              从任务题图库选择
              <span className="ml-auto text-xs text-muted-foreground">{libraryImages.length} 张</span>
            </Button>
          )}

          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            className={`flex flex-col items-center justify-center gap-1 px-4 py-5 rounded-md border-2 border-dashed cursor-pointer transition-colors ${
              dragging
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/50 hover:bg-accent/40"
            }`}
          >
            <ImagePlus className="w-5 h-5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">
              点击图标或拖拽图片到这里上传题图
            </span>
            <span className="text-[11px] text-muted-foreground/70">
              支持 PNG / JPG / JPEG / WEBP，单张不超过 5MB
            </span>
            {images.length > 0 && (
              <span className="text-[11px] text-muted-foreground/70">
                已有题图可拖拽到源码区，或复制 ![](图N) 引用
              </span>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              className="hidden"
              onChange={(e) => {
                void addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        </div>
      )}

      <Dialog open={libraryOpen} onOpenChange={setLibraryOpen}>
        <DialogContent className="max-w-3xl max-h-[82vh] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden">
          <DialogHeader>
            <DialogTitle>任务题图库</DialogTitle>
            <DialogDescription>
              选择本次 OCR 任务生成或已上传的题图，可多选后关联到当前题目。
            </DialogDescription>
          </DialogHeader>

          {libraryImages.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              本任务题图库暂无图片。
            </div>
          ) : (
            <div className="min-h-0 overflow-y-auto overflow-x-hidden pr-1">
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3 auto-rows-[8rem] sm:auto-rows-[9rem]">
              {libraryImages.map((img, i) => {
                const key = getImageKey(img) || String(i);
                const selected = selectedLibraryKeys.includes(key);
                const src = questionImageSrc(img.url || img.path);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => toggleLibraryImage(img)}
                    className={`relative h-32 sm:h-36 min-h-0 w-full rounded-lg border overflow-hidden bg-card flex items-center justify-center transition-colors ${
                      selected ? "border-primary ring-2 ring-ring/30" : "border-border hover:border-primary/60"
                    }`}
                    title={img.name || `题图库图片 ${i + 1}`}
                  >
                    {src ? (
                      <img
                        src={src}
                        alt={img.name || `题图库图片 ${i + 1}`}
                        className="max-w-full max-h-full object-contain"
                      />
                    ) : (
                      <span className="text-[11px] text-muted-foreground px-1 text-center">{img.name || "无预览"}</span>
                    )}
                    {selected && (
                      <span className="absolute top-2 right-2 w-6 h-6 rounded-full bg-primary text-primary-foreground inline-flex items-center justify-center shadow-sm">
                        <Check className="w-3.5 h-3.5" />
                      </span>
                    )}
                  </button>
                );
              })}
              </div>
            </div>
          )}

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setSelectedLibraryKeys([])}
              disabled={selectedLibraryKeys.length === 0 || selectingLibrary}
            >
              清空选择
            </Button>
            <Button
              type="button"
              onClick={confirmLibrarySelection}
              disabled={selectedLibraryKeys.length === 0 || selectingLibrary}
            >
              关联所选
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {readOnly && images.length === 0 && (
        <p className="text-xs text-muted-foreground">该题暂无关联题图。</p>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
