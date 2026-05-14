-- CreateTable
CREATE TABLE "reports" (
    "id" UUID NOT NULL,
    "report_type" TEXT NOT NULL,
    "requested_by" UUID NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'queued',
    "params" JSONB,
    "result_path" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completed_at" TIMESTAMP(3),
    "error_msg" TEXT,

    CONSTRAINT "reports_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "alerts" (
    "id" BIGSERIAL NOT NULL,
    "alert_type" TEXT NOT NULL,
    "severity" TEXT NOT NULL DEFAULT 'warning',
    "document_id" UUID,
    "message" TEXT NOT NULL,
    "expires_on" TIMESTAMP(3),
    "acknowledged" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "alerts_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "reports_status_idx" ON "reports"("status");

-- CreateIndex
CREATE INDEX "reports_user_created_at_idx" ON "reports"("requested_by", "created_at");

-- CreateIndex
CREATE INDEX "alerts_ack_created_idx" ON "alerts"("acknowledged", "created_at");

-- AddForeignKey
ALTER TABLE "reports" ADD CONSTRAINT "reports_requested_by_fkey" FOREIGN KEY ("requested_by") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
