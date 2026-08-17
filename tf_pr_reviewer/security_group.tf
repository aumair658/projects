# -----------------------------------------------------------------------------
# Security group
#
# INTENTIONAL FINDING (for review-bot testing): the ingress rule below opens
# SSH (port 22) to the entire internet (0.0.0.0/0). A review bot should flag
# this as an overly permissive / wide-open security group rule.
# -----------------------------------------------------------------------------

resource "aws_security_group" "app_sg" {
  name        = "${var.project_name}-sg"
  description = "Security group for the test EC2 instance"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH open to the world - INTENTIONALLY INSECURE"
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-sg"
  })
}
