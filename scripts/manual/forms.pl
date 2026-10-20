#!/usr/bin/env perl
# Parse server-rendered authentication forms; never executes JavaScript.
use strict; use warnings; use HTML::Parser; use JSON::PP;
my @forms; my $form; my %meta;
my $p=HTML::Parser->new(api_version=>3,start_h=>[sub {
 my ($tag,$a)=@_;
 if($tag eq 'meta' && $a->{id}) { $meta{$a->{id}}=$a->{content}//''; }
 if($tag eq 'form') { $form={id=>$a->{id}//'',action=>$a->{action}//'',method=>lc($a->{method}//'get'),fields=>{},inputs=>[]};push @forms,$form; }
 elsif($form && ($tag eq 'input' || $tag eq 'button')) {
  my $name=$a->{name}; return unless defined $name;
  my $type=lc($a->{type}//'text');push @{$form->{inputs}},{name=>$name,type=>$type};
  return if exists $a->{disabled} || $type eq 'button';
  return if ($type eq 'checkbox' || $type eq 'radio') && !exists $a->{checked};
  $form->{fields}{$name}=$a->{value}//'';
 }
},'tagname, attr'],end_h=>[sub { $form=undef if $_[0] eq 'form'; },'tagname']);
$p->parse_file($ARGV[0]); print JSON::PP->new->canonical->encode({forms=>\@forms,meta=>\%meta});
