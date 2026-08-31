import { cn } from "@/lib/utils";

/**
 * A group of fields that belong to one idea.
 *
 * Forms in this product are grouped the way a person thinks about the record -
 * who the person is, what they do, what they are qualified for - rather than
 * presented as one undifferentiated stack of labels and inputs. The heading
 * carries the group; a rule separates it from the next.
 */
export function FormSection({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3 border-t pt-4 first:border-t-0 first:pt-0", className)}>
      <div className="space-y-0.5">
        <h3 className="text-[13px] font-medium">{title}</h3>
        {description ? (
          <p className="text-[12px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}
