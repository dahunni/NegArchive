import { redirect } from "next/navigation"

/** Uploading happens in the drop zone on a roll page, or on the frames page. */
export default function UploadPage() {
  redirect("/images")
}
