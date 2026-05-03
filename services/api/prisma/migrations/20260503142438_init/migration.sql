-- CreateTable
CREATE TABLE "documents" (
    "id" UUID NOT NULL,
    "status" TEXT NOT NULL,
    "submitted_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "device_id" TEXT NOT NULL,
    "ocr_result" JSONB,

    CONSTRAINT "documents_pkey" PRIMARY KEY ("id")
);
