DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'aegis_users'::regclass
          AND conname = 'aegis_users_role_check'
          AND pg_get_constraintdef(oid) NOT ILIKE '%viewer%'
    ) THEN
        ALTER TABLE aegis_users DROP CONSTRAINT aegis_users_role_check;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'aegis_users'::regclass
          AND conname = 'aegis_users_role_check'
    ) THEN
        ALTER TABLE aegis_users
            ADD CONSTRAINT aegis_users_role_check CHECK (role IN ('operator', 'admin', 'viewer'));
    END IF;
END
$$;
