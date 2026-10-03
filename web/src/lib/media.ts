/**
 * Getting photos in: camera, gallery (Android photo picker, no storage
 * permission needed) and files. Every photo is shrunk to at most 1600 px and
 * re-encoded as JPEG: smaller uploads on rural networks, and orientation is fixed.
 */
import { Camera, MediaTypeSelection } from "@capacitor/camera";
import { isNative } from "./config";

const MAX_SIDE = 1600;
const QUALITY = 0.85;

function isCancel(err: unknown): boolean {
  return /cancel/i.test(String((err as Error)?.message ?? err));
}

async function blobFromWebPath(webPath: string | undefined): Promise<Blob | null> {
  if (!webPath) return null;
  return (await fetch(webPath)).blob();
}

/** Open a file picker. `capture` asks mobile browsers to open the camera directly. */
function pickWithInput(capture: boolean): Promise<Blob | null> {
  return new Promise(resolve => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    if (capture) input.setAttribute("capture", "environment");
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}

export async function takePhoto(): Promise<Blob | null> {
  try {
    if (!isNative) return await shrink(await pickWithInput(true));
    const photo = await Camera.takePhoto({ quality: 90, correctOrientation: true });
    return await shrink(await blobFromWebPath(photo.webPath));
  } catch (err) {
    if (isCancel(err)) return null;
    throw err;
  }
}

export async function chooseFromGallery(): Promise<Blob | null> {
  try {
    if (!isNative) return await shrink(await pickWithInput(false));
    const { results } = await Camera.chooseFromGallery({
      mediaType: MediaTypeSelection.Photo,
      allowMultipleSelection: false,
      limit: 1,
    });
    return await shrink(await blobFromWebPath(results[0]?.webPath));
  } catch (err) {
    if (isCancel(err)) return null;
    throw err;
  }
}

/** Any image file (Files app, Google Drive, WhatsApp images…). */
export async function chooseFile(): Promise<Blob | null> {
  return shrink(await pickWithInput(false));
}

export async function shrink(blob: Blob | null): Promise<Blob | null> {
  if (!blob) return null;
  try {
    const bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const out = await new Promise<Blob | null>(r => canvas.toBlob(r, "image/jpeg", QUALITY));
    return out ?? blob;
  } catch {
    return blob;   // unusual format: let the server try
  }
}
